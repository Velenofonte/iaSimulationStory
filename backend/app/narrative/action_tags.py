"""Multi-label action tags for chat epistemic metadata."""

from __future__ import annotations

import re
from typing import Literal

ActionTag = Literal["dialogue", "overt", "stealth", "hide", "private", "wait", "finding"]

_ACTION_TAG_ORDER: tuple[ActionTag, ...] = (
    "dialogue",
    "overt",
    "stealth",
    "hide",
    "private",
    "wait",
    "finding",
)

_DIALOGUE_RE = re.compile(
    r"(?:"
    r'[«"].{2,}[»"]'
    r"|\b(?:dico|chiedo|chiederei|rispondo|sussurro|mormoro|urlo|grido)\b"
    r")",
    re.IGNORECASE,
)

_STEALTH_RE = re.compile(
    r"(?i)(?:"
    r"fuori\s+da\s+(?:occhi|sguardi)|"
    r"lontano\s+(?:dagli?\s+sguardi|da\s+occhi)|"
    r"nascost|"
    r"di\s+nascosto|"
    r"in\s+segreto|"
    r"senza\s+(?:essere\s+)?(?:vist|notat)|"
    r"invisibil|"
    r"occult|"
    r"furtiv|"
    r"di\s+soppiatto|"
    r"all['\u2019]insaputa"
    r")"
)

_HIDE_RE = re.compile(
    r"(?i)(?:"
    r"\bmi\s+nascondo\b|"
    r"\bnascondermi\b|"
    r"\bnascondo\b|"
    r"\bmi\s+celo\b"
    r")"
)

_PRIVATE_RE = re.compile(r"\*[^*]+\*")

_WAIT_RE = re.compile(
    r"(?i)\baspetto\b|\battendo\b|\bfinch[eé]\b|\bfino\s+a\s+quando\b"
)


def tag_player_action(
    player_action: str,
    *,
    stance: str | None = None,
) -> list[ActionTag]:
    """Heuristic multi-label tags for a player beat.

    Visibility: ``stealth``/``hide`` xor ``overt`` — stealth cues win.
    """
    msg = (player_action or "").strip()
    tags: set[ActionTag] = set()
    if not msg and stance != "wait":
        return []

    has_dialogue = bool(_DIALOGUE_RE.search(msg))
    if has_dialogue:
        tags.add("dialogue")

    if _PRIVATE_RE.search(msg):
        tags.add("private")

    stealth = bool(_STEALTH_RE.search(msg))
    hide = bool(_HIDE_RE.search(msg))
    if stealth:
        tags.add("stealth")
    if hide:
        tags.add("hide")

    is_wait = stance == "wait" or (
        bool(_WAIT_RE.search(msg)) and not has_dialogue
    )
    if is_wait:
        tags.add("wait")

    covert = "stealth" in tags or "hide" in tags
    if covert:
        tags.discard("overt")
    elif msg and not (is_wait and tags <= {"wait", "private"}):
        # Public physical/spoken beat when not covert.
        if has_dialogue or not is_wait or stance in {None, "action", "passive"}:
            if not is_wait or has_dialogue:
                tags.add("overt")

    if not tags and msg:
        tags.add("overt")
    if stance == "wait" and not tags:
        tags.add("wait")

    return _ordered(tags)


def _ordered(tags: set[ActionTag]) -> list[ActionTag]:
    return [t for t in _ACTION_TAG_ORDER if t in tags]


def ensure_tags(
    content: str,
    tags: list[str] | None,
    *,
    stance: str | None = None,
) -> list[ActionTag]:
    """Use stored tags if present; otherwise retag from content (legacy chat)."""
    if tags:
        cleaned: set[ActionTag] = set()
        for raw in tags:
            t = str(raw).strip().lower()
            if t in _ACTION_TAG_ORDER:
                cleaned.add(t)  # type: ignore[arg-type]
        if "stealth" in cleaned or "hide" in cleaned:
            cleaned.discard("overt")
        if cleaned:
            return _ordered(cleaned)
    return tag_player_action(content, stance=stance)
