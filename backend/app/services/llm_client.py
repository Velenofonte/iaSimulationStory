import json
from typing import Any, TypeVar

from google import genai
from google.genai import types
from openai import OpenAI
from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)

_LLM_TIMEOUT_S = 90.0

_GEMINI_SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
]


def _is_gemini_model(model: str) -> bool:
    return model.lower().startswith("gemini")


def _is_openrouter_model(model: str) -> bool:
    # Slug OpenRouter: "provider/model" o alias "~provider/model-latest"
    name = model.strip()
    return name.startswith("~") or "/" in name


def _is_gpt56_luna(model: str) -> bool:
    """openai/gpt-5.6-luna and -pro (OpenRouter slug or bare id)."""
    name = model.strip().lower().lstrip("~").rsplit("/", 1)[-1]
    return name.startswith("gpt-5.6-luna")


def _is_deepseek_model(model: str) -> bool:
    slug = model.strip().lower().lstrip("~")
    return slug.startswith("deepseek/") or slug.startswith("deepseek-")


def _should_disable_reasoning(model: str) -> bool:
    # Luna defaults to medium thinking; DeepSeek V4 thinking-on returns empty content.
    return _is_gpt56_luna(model) or _is_deepseek_model(model)


def _json_schema_response_format(schema: type[BaseModel]) -> dict[str, Any]:
    # strict false: TurnResolution uses dict[str, ...] (additionalProperties).
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "strict": False,
            "schema": schema.model_json_schema(),
        },
    }


def _openai_chat_kwargs(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_output_tokens: int = 0,
    response_schema: type[BaseModel] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    if max_output_tokens > 0:
        kwargs["max_tokens"] = max_output_tokens
    extra_body: dict[str, Any] = {}
    if _should_disable_reasoning(model):
        extra_body["reasoning"] = {"enabled": False, "effort": "none"}
        extra_body["reasoning_effort"] = "none"
        extra_body["thinking"] = {"type": "disabled"}
    if response_schema is not None:
        if _is_gpt56_luna(model):
            kwargs["response_format"] = _json_schema_response_format(response_schema)
        elif _is_deepseek_model(model):
            # json_object is widely supported; json_schema 400s on some V4 hosts.
            kwargs["response_format"] = {"type": "json_object"}
    if _is_openrouter_model(model):
        provider: dict[str, Any] = {"sort": "latency"}
        if _is_gpt56_luna(model):
            # Flex is ~6s TTFT; Bedrock/standard OpenAI are much faster.
            provider["ignore"] = ["OpenAI Flex"]
        extra_body["provider"] = provider
    if extra_body:
        kwargs["extra_body"] = extra_body
    return kwargs


def _message_text(message: Any) -> str:
    """Prefer visible content; DeepSeek thinking often leaves content empty."""
    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
                if text:
                    parts.append(str(text))
        joined = "".join(parts).strip()
        if joined:
            return joined
    for attr in ("reasoning_content", "reasoning"):
        val = getattr(message, attr, None)
        if isinstance(val, str) and val.strip():
            return val
    parsed = getattr(message, "parsed", None)
    if parsed is not None:
        if isinstance(parsed, str) and parsed.strip():
            return parsed
        try:
            dumped = json.dumps(parsed, ensure_ascii=False)
        except TypeError:
            dumped = ""
        if dumped and dumped not in ("null", "{}"):
            return dumped
    return content if isinstance(content, str) else ""


class LLMClient:
    def __init__(self) -> None:
        self.last_usage: dict[str, Any] | None = None
        self._openai_client: OpenAI | None = None
        self._openrouter_client: OpenAI | None = None
        self._gemini_native: genai.Client | None = None

        if settings.openai_api_key:
            kwargs: dict[str, Any] = {}
            if getattr(settings, "llm_api_base_url", None):
                kwargs["base_url"] = settings.llm_api_base_url
            self._openai_client = OpenAI(
                api_key=settings.openai_api_key,
                timeout=_LLM_TIMEOUT_S,
                **kwargs,
            )

        if settings.openrouter_api_key:
            self._openrouter_client = OpenAI(
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_api_base_url or "https://openrouter.ai/api/v1",
                timeout=_LLM_TIMEOUT_S,
                default_headers={
                    "HTTP-Referer": "https://github.com/wiki-overlord",
                    "X-Title": "Wiki Overlord",
                },
            )

        if settings.gemini_api_key:
            # SDK nativo: safety_settings non funzionano sull'endpoint OpenAI-compatible
            self._gemini_native = genai.Client(api_key=settings.gemini_api_key)

    @property
    def available(self) -> bool:
        return (
            self._openai_client is not None
            or self._openrouter_client is not None
            or self._gemini_native is not None
        )

    # Shared fragments appended after the parent prompt (order matters).
    _PROMPT_SHARED: dict[str, tuple[str, ...]] = {
        "turn_resolve": (
            "player_action_grammar",
            "npc_epistemic",
            "id_registry",
        ),
        "narrative_render": (
            "player_action_grammar",
            "npc_epistemic",
        ),
        "review_present": ("id_registry",),
    }

    def load_prompt(self, name: str) -> str:
        """Load a system prompt, composing optional `_shared/` fragments."""
        return self.compose_prompt(name)

    def compose_prompt(self, name: str) -> str:
        """Parent markdown + shared fragments for that prompt name."""
        path = settings.prompts_dir / f"{name}.md"
        if not path.exists():
            return ""
        parts = [path.read_text(encoding="utf-8").rstrip()]
        shared_dir = settings.prompts_dir / "_shared"
        for frag in self._PROMPT_SHARED.get(name, ()):
            frag_path = shared_dir / f"{frag}.md"
            if frag_path.exists():
                parts.append(frag_path.read_text(encoding="utf-8").rstrip())
        return "\n\n".join(parts) + "\n"

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float = 0.8,
        response_schema: type[BaseModel] | None = None,
    ) -> str:
        self.last_usage = None
        resolved_model = model or settings.llm_model_narrative
        if _is_gemini_model(resolved_model):
            if not self._gemini_native:
                return self._mock_response(user)
            return self._complete_gemini(
                system=system,
                user=user,
                model=resolved_model,
                temperature=temperature,
            )
        client = self._client_for_model(resolved_model)
        if client is None:
            return self._mock_response(user)
        kwargs = _openai_chat_kwargs(
            model=resolved_model,
            system=system,
            user=user,
            temperature=temperature,
            max_output_tokens=settings.llm_max_output_tokens,
            response_schema=response_schema,
        )
        response = client.chat.completions.create(**kwargs)
        self.last_usage = self._extract_usage(response)
        message = response.choices[0].message
        text = _message_text(message)
        if not (text or "").strip():
            finish = getattr(response.choices[0], "finish_reason", None)
            print(
                f"[llm] empty content model={resolved_model} finish={finish!r} "
                f"schema={response_schema.__name__ if response_schema else None}"
            )
        return text or ""

    def _client_for_model(self, model: str) -> OpenAI | None:
        if _is_openrouter_model(model):
            return self._openrouter_client
        return self._openai_client

    def _complete_gemini(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float,
    ) -> str:
        assert self._gemini_native is not None
        config_kwargs: dict[str, Any] = {
            "system_instruction": system,
            "temperature": temperature,
            "safety_settings": _GEMINI_SAFETY_SETTINGS,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if settings.llm_max_output_tokens > 0:
            config_kwargs["max_output_tokens"] = settings.llm_max_output_tokens
        response = self._gemini_native.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        self.last_usage = self._extract_gemini_usage(response)
        return (getattr(response, "text", None) or "").strip()

    def _extract_gemini_usage(self, response: Any) -> dict[str, Any] | None:
        meta = getattr(response, "usage_metadata", None)
        if meta is None:
            return None
        prompt = getattr(meta, "prompt_token_count", None) or 0
        candidates = getattr(meta, "candidates_token_count", None) or 0
        total = getattr(meta, "total_token_count", None) or (prompt + candidates)
        cached = getattr(meta, "cached_content_token_count", None) or 0
        return {
            "prompt_tokens": prompt,
            "completion_tokens": candidates,
            "total_tokens": total,
            "cached_tokens": cached,
        }

    def _extract_usage(self, response: Any) -> dict[str, Any] | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        out: dict[str, Any] = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", None) or 0,
            "total_tokens": getattr(usage, "total_tokens", None) or 0,
            "cached_tokens": 0,
        }
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            out["cached_tokens"] = getattr(details, "cached_tokens", None) or 0
        elif isinstance(usage, dict):
            out["prompt_tokens"] = usage.get("prompt_tokens") or 0
            out["completion_tokens"] = usage.get("completion_tokens") or 0
            out["total_tokens"] = usage.get("total_tokens") or 0
            ptd = usage.get("prompt_tokens_details") or {}
            if isinstance(ptd, dict):
                out["cached_tokens"] = ptd.get("cached_tokens") or 0
        return out

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> T:
        raw = self.complete(
            system=system,
            user=user,
            model=model,
            temperature=temperature,
            response_schema=schema,
        )
        payload = self.extract_json(raw)
        return schema.model_validate(payload)

    @staticmethod
    def _escape_control_chars_in_json_strings(text: str) -> str:
        """Escape raw control chars inside JSON string literals (common LLM flaw)."""
        out: list[str] = []
        in_string = False
        escape = False
        for ch in text:
            if escape:
                out.append(ch)
                escape = False
                continue
            if ch == "\\" and in_string:
                out.append(ch)
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                out.append(ch)
                continue
            if in_string and ord(ch) < 0x20:
                if ch == "\n":
                    out.append("\\n")
                elif ch == "\r":
                    out.append("\\r")
                elif ch == "\t":
                    out.append("\\t")
                else:
                    out.append(f"\\u{ord(ch):04x}")
                continue
            out.append(ch)
        return "".join(out)

    def extract_json(self, raw: str) -> Any:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        candidates = [text]
        start = text.find("{")
        if start > 0:
            candidates.append(text[start:])
        elif start == 0:
            pass
        else:
            raise json.JSONDecodeError("No JSON object found", text, 0)

        last_err: json.JSONDecodeError | None = None
        for candidate in candidates:
            for attempt in (candidate, self._escape_control_chars_in_json_strings(candidate)):
                try:
                    return json.loads(attempt)
                except json.JSONDecodeError as exc:
                    last_err = exc
                try:
                    obj, _end = json.JSONDecoder().raw_decode(attempt)
                    return obj
                except json.JSONDecodeError as exc:
                    last_err = exc
        assert last_err is not None
        raise last_err

    def _mock_response(self, user: str) -> str:
        text = user.strip()
        # Character creation (markdown sheet, not JSON)
        if "CHARACTER_ID:" in text and "RACE:" in text:
            cid = "hero"
            name = "Avventuriero"
            race = "human"
            location = "e-rantel"
            for line in text.splitlines():
                if line.startswith("CHARACTER_ID:"):
                    cid = line.split(":", 1)[1].strip() or cid
                elif line.startswith("NAME:"):
                    name = line.split(":", 1)[1].strip() or name
                elif line.startswith("RACE:"):
                    race = line.split(":", 1)[1].strip() or race
                elif line.startswith("LOCATION:"):
                    location = line.split(":", 1)[1].strip() or location
            return (
                f"---\nid: {cid}\nname: {name}\ntype: character\ntier: minimal\n"
                f"role: player\nrace: {race}\nlocation: {location}\n---\n\n"
                f"# Personalita\n{name} e' un personaggio custom determinato.\n\n"
                f"# Aspetto fisico\nTratti tipici della razza {race}.\n\n"
                "# Obiettivi\nEsplorare il Nuovo Mondo e affermarsi.\n\n"
                "# Capacita di combattimento\nCompetente secondo i dettagli forniti.\n\n"
                "# Knowledge scope\nsa: conoscenze di base della propria origine.\n"
                "non sa: segreti nascosti del setting.\n\n"
                "# Relazione col giocatore\n0\n\n"
                "# Memorie\n\n"
                "# Open threads\n"
            )

        payload: Any = None
        if text.startswith("{"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None

        # Pass 2 render: scene_brief present, or render-only fields without full request
        if isinstance(payload, dict):
            if "scene_brief" in payload or (
                "player_action" in payload
                and "canon_facts" in payload
                and "active_arc" not in payload
                and "world_pages" not in payload
            ):
                return json.dumps(
                    {
                        "text": (
                            "Il mondo di Overlord ti accoglie. Sei tra mercanti e avventurieri; "
                            "l'aria odora di legna e birra."
                        )
                    },
                    ensure_ascii=False,
                )
            # Pass 1 resolve / NarrativeRequest
            if "player_action" in payload or "canon_facts" in payload:
                return json.dumps(
                    {
                        "time": {"bucket": "istantanea", "minutes": 3},
                        "location": None,
                        "present": None,
                        "spells": [],
                        "scene_brief": [
                            "Il mondo di Overlord ti accoglie tra mercanti e avventurieri."
                        ],
                    },
                    ensure_ascii=False,
                )

        # Legacy single-pass NarrativeReply mock
        if '"player_action"' in text or "NarrativeRequest" in text or '"canon_facts"' in text:
            if '"scene_brief"' in text and '"active_arc"' not in text:
                return json.dumps(
                    {
                        "text": (
                            "Il mondo di Overlord ti accoglie. Sei tra mercanti e avventurieri; "
                            "l'aria odora di legna e birra."
                        )
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "time": {"bucket": "istantanea", "minutes": 3},
                    "location": None,
                    "present": None,
                    "spells": [],
                    "scene_brief": [
                        "Il mondo di Overlord ti accoglie tra mercanti e avventurieri."
                    ],
                },
                ensure_ascii=False,
            )
        if "JSON" in text or "json" in text or "Restituisci JSON" in text:
            return "{}"
        return (
            "Il mondo di Overlord ti accoglie. Sei a E-Rantel, tra mercanti e avventurieri. "
            "L'aria odora di legna e birra."
        )
