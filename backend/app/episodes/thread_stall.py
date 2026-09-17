"""Detect when the player keeps pushing the same thread without structural progress."""

from __future__ import annotations

import re

from app.config import settings
from app.models.narrative import NarrativeChatTurn

_STOP = frozenset(
    {
        "aspetto",
        "aspetta",
        "chiedo",
        "continuo",
        "cosa",
        "come",
        "dico",
        "dove",
        "facciamo",
        "faccio",
        "guarda",
        "guardi",
        "guardo",
        "perche",
        "perché",
        "posso",
        "provo",
        "quando",
        "quello",
        "questa",
        "questo",
        "quindi",
        "rayan",
        "sento",
        "sono",
        "stesso",
        "tutto",
        "verso",
        "voglio",
        "anche",
        "alla",
        "alle",
        "allo",
        "ancora",
        "cerco",
        "della",
        "delle",
        "dello",
        "della",
        "nella",
        "nelle",
        "nello",
        "sulla",
        "sulle",
        "sullo",
        "alla",
        "solo",
        "sono",
        "alla",
        "poi",
        "mentre",
        "dopo",
        "prima",
        "bene",
        "meglio",
        "molto",
        "poco",
        "tutto",
        "nulla",
        "niente",
        "solo",
        "sempre",
        "adesso",
        "oggi",
        "ieri",
        "domani",
        "qui",
        "li",
        "loro",
        "lui",
        "lei",
        "noi",
        "voi",
        "essere",
        "avere",
        "fare",
        "dire",
        "andare",
        "venire",
        "stare",
        "dare",
        "vedere",
        "sapere",
        "volere",
        "dovere",
        "potere",
    }
)


def _focus_tokens(text: str) -> set[str]:
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").casefold())
    return {t for t in cleaned.split() if len(t) >= 4 and t not in _STOP}


def detect_thread_stall(
    chat_recent: list[NarrativeChatTurn],
    player_action: str,
    situations: list[str],
    *,
    threshold: int | None = None,
) -> str:
    """Return a resolver hint when the same focus repeats without tracked progress."""
    min_turns = max(2, int(threshold or settings.thread_stall_turns or 3))
    user_msgs = [t.content for t in chat_recent if (t.role or "").strip().lower() == "user"]
    user_msgs.append(player_action or "")
    if len(user_msgs) < min_turns:
        return ""

    current = _focus_tokens(player_action)
    if not current:
        return ""

    streak = 0
    overlap_terms: set[str] = set()
    focus = set(current)
    for msg in reversed(user_msgs):
        tokens = _focus_tokens(msg)
        shared = focus & tokens
        if not shared:
            break
        streak += 1
        overlap_terms |= shared
        focus = shared

    if streak < min_turns:
        return ""

    # If situations already name this focus, the thread is at least registered — still
    # nudge when the player keeps pushing, but soften the wording slightly.
    tracked = any(
        any(term in (sit or "").casefold() for term in overlap_terms) for sit in situations
    )
    focus_label = ", ".join(sorted(overlap_terms)[:4])
    tracked_note = (
        " (il filo compare in situations ma non sembra avanzare)"
        if tracked
        else " (assente da situations: registralo se resta rilevante)"
    )
    return (
        f"Il PG insiste sullo stesso filo ({focus_label}) da {streak} turni consecutivi"
        f"{tracked_note}. Nel scene_brief proponi una spinta concreta per andare avanti "
        f"(nuovo indizio osservabile, reazione NPC, costo, scelta, deferimento esplicito) "
        f"oppure una chiusura leggibile se il mondo non collabora — non e' obbligatorio "
        f"chiudere, ma serve una via chiara. VIETATO rispondere solo con 'non funziona "
        f"ancora' / 'resta muto' / eco atmosferica senza un fatto nuovo nel brief."
    )
