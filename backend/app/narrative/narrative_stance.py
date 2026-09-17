"""Detect passive vs active player turns and trim narrative context."""

from __future__ import annotations

import re

from app.models.narrative import NarrativeChatTurn

_ACTION_RE = re.compile(
    r"(?i)\b("
    r"vado|corro|attacco|parlo|dico|chied(?:o|erei)|ordino|url|lancio|uso|intervengo|"
    r"mi\s+avvicino|mi\s+allontano|entro|esco|colpisco|grido|sussurro|mormoro|"
    r"porgo|dono|offro|consegno"
    r")\b"
)
# Quoted speech / address → the PG is acting, even if they also "guardano" someone.
_DIALOGUE_RE = re.compile(
    r"(?:"
    r'[«"].{2,}[»"]'  # «...» or "..."
    r"|\b(?:a|verso|guardando|guardo|guardare)\s+\w+.+\b(?:dico|chiedo|chiederei)\b"
    r")",
    re.IGNORECASE,
)
_PASSIVE_RE = re.compile(
    r"(?i)(?:"
    r"(?:continuo\s+a\s+)?(?:guard|osserv|scrut)"
    r"|aspetto(?:\s+e\s+guard|\s+che)?"
    r"|rimango\s+(?:immobile|fermo|a\s+guard)"
    r"|resto\s+(?:immobile|fermo|a\s+guard)"
    r"|tengo\s+d'?occhio"
    r"|seguo\s+(?:la\s+)?(?:battaglia|scena)"
    r"|non\s+intervengo"
    r")"
)
_WAIT_UNTIL_RE = re.compile(
    r"(?i)(?:"
    r"\baspetto\b"
    r"|\battendo\b"
    r"|\bfinch[eé]\b"
    r"|\bfino\s+a\s+quando\b"
    r"|\bfino\s+al(?:la|lo|l')?\b"
    r"|\bcontinuo\b.+\bfinch[eé]\b"
    r")"
)


def detect_stance(player_action: str) -> str:
    """Classify active actions, observation, and wait-until intents."""
    msg = (player_action or "").strip()
    if not msg:
        return "action"
    # Dialogue / address overrides wait-ish wording only when there is speech.
    # Pure "aspetto la risposta di X" stays wait (no quotes).
    if _WAIT_UNTIL_RE.search(msg) and not _DIALOGUE_RE.search(msg):
        return "wait"
    if _DIALOGUE_RE.search(msg) or _ACTION_RE.search(msg):
        return "action"
    if _PASSIVE_RE.search(msg):
        return "passive"
    return "action"


def trim_chat_for_passive_render(chat: list[NarrativeChatTurn]) -> list[NarrativeChatTurn]:
    """Riduce eco sul passivo TENENDO l'ultimo assistant (continuita' obbligatoria).

    Prima si rimuovevano gli ultimi 1-2 assistant: il render non vedeva l'impatto
    appena narrato e poteva riavvolgere eventi (meteorite ancora in cielo, ecc.).
    Ora si puo' togliere al massimo un assistant *penultimo*, mai l'ultimo beat.
    """
    trimmed = list(chat)
    assistant_idxs = [i for i, t in enumerate(trimmed) if t.role == "assistant"]
    if len(assistant_idxs) >= 2:
        # Togli solo il penultimo assistant; l'ultimo resta per il canone del beat.
        del trimmed[assistant_idxs[-2]]
    return trimmed


def last_assistant_message(chat: list[NarrativeChatTurn]) -> str:
    for turn in reversed(chat):
        if turn.role == "assistant":
            return turn.content
    return ""


_QUOTE_CHUNK_RE = re.compile(r"[«\"]([^»\"]{12,})[»\"]")


def compress_repeated_narrative(
    new_text: str,
    prior_assistant: str,
    *,
    fallback: str = "La situazione evolve dopo qualche istante.",
) -> str:
    """Remove sentences already narrated in the previous assistant turn."""
    new_text = (new_text or "").strip()
    prior = (prior_assistant or "").strip()
    if not new_text or not prior:
        return new_text

    prior_lower = prior.lower()
    prior_quotes = {
        m.group(1).strip().lower() for m in _QUOTE_CHUNK_RE.finditer(prior)
    }
    parts = re.split(r"(?<=[.!?…])\s+", new_text)
    kept: list[str] = []
    for part in parts:
        sentence = part.strip()
        if not sentence:
            continue
        key = sentence.lower()[:100]
        if key and key in prior_lower:
            continue
        # Drop recycled NPC dialogue even if the surrounding prose differs.
        recycled_quote = False
        for qm in _QUOTE_CHUNK_RE.finditer(sentence):
            chunk = qm.group(1).strip().lower()
            if chunk in prior_quotes:
                recycled_quote = True
                break
            if len(chunk) >= 20 and chunk[:80] in prior_lower:
                recycled_quote = True
                break
        if recycled_quote:
            continue
        words = [w for w in re.findall(r"\w+", sentence.lower()) if len(w) > 3]
        if len(words) >= 5:
            hits = sum(1 for w in words if w in prior_lower)
            if hits / len(words) >= 0.72:
                continue
        kept.append(sentence)

    if not kept:
        return fallback
    return " ".join(kept)
