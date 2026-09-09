from __future__ import annotations

import re

from app.config import settings
from app.models.turn import NarrativeRenderRequest, NarrativeRenderResult
from app.services.llm_client import LLMClient
from app.services.token_estimate import estimate_tokens

_TRAILING_PROMPT_RE = re.compile(
    r"(?:\n\s*)?(?:\*+)?\s*Cosa fai\??\s*(?:\*+)?\s*$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"\S+")


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def clamp_words(text: str, max_words: int) -> str:
    """Taglia a max_words preferendo un fine frase; 0 = no-op."""
    if max_words <= 0 or not text:
        return text
    words = list(_WORD_RE.finditer(text))
    if len(words) <= max_words:
        return text.strip()
    cut_at = words[max_words - 1].end()
    truncated = text[:cut_at].rstrip()
    # Preferisci l'ultima fine frase completa dentro il taglio
    best = 0
    for m in re.finditer(r"[.!?…][»\"']?", truncated):
        best = m.end()
    if best >= max(20, cut_at // 3):
        return truncated[:best].rstrip()
    return truncated


class NarrativeRenderer:
    def __init__(self, *, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self.last_tokens: tuple[int, int, int] = (0, 0, 0)

    def render(self, request: NarrativeRenderRequest) -> str:
        system = self.llm.load_prompt("narrative_render")
        max_words = int(settings.narrative_max_words or 0)
        if max_words > 0:
            system = (
                f"{system.rstrip()}\n\n"
                f"## Limite lunghezza (vincolante)\n"
                f"- Il campo `text` deve restare entro **{max_words} parole** (spazi inclusi nel conteggio parole).\n"
                f"- Privilegia delta di scena e battute utili; niente atmosfera ripetuta o elenchi inutili.\n"
                f"- Non omettere le `\"...\"` / azioni / `[magie]` del PG per rispettare il tetto: "
                f"comprimi il resto.\n"
            )
        user_prompt = request.model_dump_json()
        tokens_system = estimate_tokens(system)
        tokens_user = estimate_tokens(user_prompt)
        model = settings.llm_model_render or settings.llm_model_narrative
        try:
            result = self.llm.complete_json(
                system=system,
                user=user_prompt,
                schema=NarrativeRenderResult,
                model=model,
                temperature=0.8,
            )
            text = self._sanitize(result.text)
        except Exception as exc:
            print(f"[narrative_render] complete_json failed ({model}): {type(exc).__name__}: {exc}")
            try:
                raw = self.llm.complete(
                    system=system, user=user_prompt, model=model, temperature=0.8
                )
            except Exception as retry_exc:
                print(
                    f"[narrative_render] retry complete failed ({model}): "
                    f"{type(retry_exc).__name__}: {retry_exc}"
                )
                raw = ""
            text = self._fallback(raw, request)

        text = clamp_words(text, max_words)

        usage = self.llm.last_usage
        if usage and usage.get("prompt_tokens"):
            prompt = int(usage["prompt_tokens"])
            total_est = tokens_system + tokens_user
            if total_est > 0:
                tokens_system = max(1, int(round(prompt * tokens_system / total_est)))
                tokens_user = max(0, prompt - tokens_system)
            else:
                tokens_system, tokens_user = prompt, 0
            self.last_tokens = (prompt, tokens_system, tokens_user)
        else:
            self.last_tokens = (
                tokens_system + tokens_user,
                tokens_system,
                tokens_user,
            )
        return text

    def _sanitize(self, text: str) -> str:
        stripped = _TRAILING_PROMPT_RE.sub("", (text or "").strip()).rstrip()
        if not stripped or stripped.lstrip().startswith("{"):
            return "Il mondo resta in sospeso. Continua."
        return stripped

    def _fallback(self, raw: str, request: NarrativeRenderRequest) -> str:
        try:
            payload = self.llm.extract_json(raw)
            if isinstance(payload, dict) and payload.get("text"):
                print("[narrative_render] fallback: recovered text from retry JSON")
                return self._sanitize(str(payload["text"]))
            keys = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
            preview = (raw or "").replace("\n", " ")[:180]
            print(
                f"[narrative_render] fallback: retry JSON missing text "
                f"(keys={keys}); raw_preview={preview!r}"
            )
        except Exception as exc:
            preview = (raw or "").replace("\n", " ")[:180]
            print(
                f"[narrative_render] fallback: retry JSON unusable "
                f"({type(exc).__name__}: {exc}); raw_preview={preview!r}"
            )
        cleaned = _TRAILING_PROMPT_RE.sub("", (raw or "").strip()).rstrip()
        if cleaned and not cleaned.lstrip().startswith("{"):
            print("[narrative_render] fallback: using raw non-JSON text")
            return cleaned
        brief = " ".join(request.scene_brief).strip()
        if brief:
            print(
                f"[narrative_render] fallback: using scene_brief "
                f"({len(request.scene_brief)} bullets)"
            )
            return brief
        print("[narrative_render] fallback: placeholder (no brief)")
        return "Il mondo resta in sospeso. Continua."
