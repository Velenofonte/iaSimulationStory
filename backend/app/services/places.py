"""Normalize location ids so wiki, fronts, and LLM aliases match."""

from __future__ import annotations

_PLACE_ALIASES = {
    "carne-village": "carne",
    "carnevillage": "carne",
    "carne village": "carne",
    "villaggio della carne": "carne",
    "villaggio di carne": "carne",
    "carne-outskirts": "carne",
    "dintorni di carne": "carne",
    "margini di carne": "carne",
}


def normalize_place_id(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    key = text.lower().replace("_", "-")
    key = " ".join(key.split())
    return _PLACE_ALIASES.get(key, key)


def player_at_place(player_location: str, place: str) -> bool:
    """True when player location and beat place refer to the same site."""
    a = normalize_place_id(player_location)
    b = normalize_place_id(place)
    if not a or not b:
        return False
    return a == b
