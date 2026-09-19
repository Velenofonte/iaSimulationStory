from __future__ import annotations

import re

from app.config import settings
from app.models.turn import NarrativeRenderRequest, NarrativeRenderResult
from app.llm.llm_client import LLMClient
from app.narrative.token_estimate import estimate_tokens

_TRAILING_PROMPT_RE = re.compile(
    r"(?:\n\s*)?(?:\*+)?\s*Cosa fai\??\s*(?:\*+)?\s*$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"\S+")
_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ]{4,}")
_STOPWORDS = frozenset(
    {
        "della",
        "delle",
        "dello",
        "degli",
        "nella",
        "nelle",
        "nello",
        "negli",
        "alla",
        "alle",
        "allo",
        "agli",
        "come",
        "sono",
        "essere",
        "questa",
        "questo",
        "questi",
        "queste",
        "anche",
        "dopo",
        "prima",
        "mentre",
        "quando",
        "dove",
        "molto",
        "poco",
        "tutto",
        "tutti",
        "tutte",
        "from",
        "with",
        "that",
        "this",
        "have",
        "been",
    }
)


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


def summary_key_tokens(
    summary: str,
    limit: int = 3,
    *,
    exclude: set[str] | None = None,
) -> list[str]:
    """Rough content tokens from a fired beat bullet (for render reflection check).

    ``exclude`` drops words already part of the scene (present cast, ambient
    roles, place ids): otherwise a summary about an event would look "reflected"
    just because the actor's name is mentioned again.
    """
    blocked = {w.casefold() for w in (exclude or set())}
    out: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(summary or ""):
        key = raw.casefold()
        if key in _STOPWORDS or key in seen or key in blocked:
            continue
        seen.add(key)
        out.append(raw)
        if len(out) >= limit:
            break
    return out


# Generic displacement / off-site closure cues (no pack-specific means).
_DISPLACE_RE = re.compile(
    r"(?i)\b("
    r"piu['’]?\s+a\s+nord|piu['’]?\s+a\s+sud|piu['’]?\s+a\s+est|piu['’]?\s+a\s+ovest|"
    r"piu['’]?\s+lontano|lontano\s+da\s+(?:qui|voi|te)|"
    r"altro\s+tratto|altro\s+settore|dall['’]?\s*altra\s+parte|"
    r"altrove|gia['’]?\s+(?:successo|accaduto|chiuso|chiusa|sparato)|"
    r"ha\s+gia['’]?\s+(?:aperto|aperta|chiuso|chiusa|fatto)|"
    r"successe\s+(?:a\s+nord|a\s+sud|lontano|altrove)|"
    r"accaduto\s+(?:a\s+nord|a\s+sud|lontano|altrove)"
    r")\b"
)


def live_outcome_displaced(text: str, *, front_live: dict | None) -> bool:
    """True when prose closes/moves a live beat outcome off the player's scene."""
    if not front_live:
        return False
    return bool(_DISPLACE_RE.search(text or ""))


def fired_summaries_reflected(
    text: str,
    summaries: list[str],
    *,
    exclude: set[str] | None = None,
) -> bool:
    """True when prose roughly reflects the first fired summary (2–3 key tokens)."""
    if not summaries:
        return True
    tokens = summary_key_tokens(str(summaries[0]), limit=3, exclude=exclude)
    if not tokens:
        return True
    fold = (text or "").casefold()
    hits = sum(1 for t in tokens if t.casefold() in fold)
    need = 2 if len(tokens) >= 2 else 1
    return hits >= need


def scene_name_tokens(request: NarrativeRenderRequest) -> set[str]:
    """Words already in the scene (cast, ambient roles, place) — not event proof."""
    out: set[str] = set()
    facts = request.canon_facts

    def add(value: object) -> None:
        for word in _TOKEN_RE.findall(str(value or "")):
            out.add(word.casefold())

    for cid in list(facts.present or []) + list(request.acting_cast or []):
        add(str(cid).replace("-", " ").replace("_", " "))
    add(str(facts.location or "").replace("-", " ").replace("_", " "))
    for line in list(facts.offscreen or []):
        add(line)
    extra = facts.extra if isinstance(facts.extra, dict) else {}
    ambient = extra.get("location_ambient")
    if isinstance(ambient, dict):
        for roles in ambient.values():
            for role in roles or []:
                add(role)
    elif isinstance(ambient, list):
        for role in ambient:
            add(role)
    for card in list(request.character_cards or []):
        add(getattr(card, "name", None) or getattr(card, "id", None))
    return out


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
        text = self._complete_once(system, request)
        text = clamp_words(text, max_words)

        summaries = list(request.fired_beat_summaries or [])
        extra = {}
        try:
            extra = dict(request.canon_facts.extra or {})
        except Exception:
            extra = {}
        front_live = extra.get("front_live") if isinstance(extra, dict) else None

        need_retry = False
        retry_reason = ""
        if summaries and not fired_summaries_reflected(
            text, summaries, exclude=scene_name_tokens(request)
        ):
            need_retry = True
            retry_reason = "omesso fired_beat_summaries"
        elif live_outcome_displaced(text, front_live=front_live if isinstance(front_live, dict) else None):
            need_retry = True
            retry_reason = "esito live spostato/chiuso altrove"

        if need_retry:
            retry_system = (
                f"{system.rstrip()}\n\n"
                f"## Retry vincolante ({retry_reason})\n"
                "- Integra i fatti **nella scena del PG** (stessa location / sotto-luogo).\n"
                "- Il fatto va mostrato come **accaduto qui**, non come minaccia futura "
                "o nome ripetuto dell'attore.\n"
                "- Se `extra.front_live`: la pressione e' in corso QUI; VIETATO chiuderla "
                "come gia' accaduta lontano / altro tratto / altro settore.\n"
                "- Se arrivano `fired_beat_summaries`, il fatto e' compiuto: non lasciarlo "
                "come dialogo aperto o attesa.\n"
                "- Se `scene_brief` descrive l'esito, narra QUELLO (non un altro mezzo "
                "assente dal brief).\n"
                "- Stance wait: atterra; VIETATO un altro telegrafo incrementale.\n"
            )
            text = self._complete_once(retry_system, request)
            text = clamp_words(text, max_words)

        return text

    def _complete_once(self, system: str, request: NarrativeRenderRequest) -> str:
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
