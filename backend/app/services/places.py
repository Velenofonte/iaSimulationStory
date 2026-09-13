"""Normalize location ids so wiki, fronts, and LLM aliases match."""

from __future__ import annotations

import re

_PLACE_ALIASES = {
    "carne-village": "carne",
    "carnevillage": "carne",
    "carne village": "carne",
    "villaggio della carne": "carne",
    "villaggio di carne": "carne",
    "carne-outskirts": "carne",
    "dintorni di carne": "carne",
    "margini di carne": "carne",
    # Guild: faction id must never be stored as player.location.
    "adventurers-guild": "gilda-avventurieri",
    "adventurersguild": "gilda-avventurieri",
    "adventurers guild": "gilda-avventurieri",
    "sede-della-gilda": "gilda-avventurieri",
    "sede della gilda": "gilda-avventurieri",
    "gilda-avventurieri": "gilda-avventurieri",
    "gilda": "gilda-avventurieri",
}

_TRAVEL_RE = re.compile(
    r"(?:"
    r"\b(?:vado|parto|partiamo)\b"
    r"|mi\s+(?:incammino|dirigo|avvio)"
    r"|me\s+ne\s+vado"
    r"|\b(?:lascio|abbandono|raggiungo)\b"
    r"|cammino\s+verso"
    r"|esco\s+(?:da|dal|dalla|dall['’])"
    r"|torno\s+(?:a|al|alla|all['’])"
    r")",
    re.IGNORECASE,
)


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


def is_travel_intent(player_action: str) -> bool:
    """True when the player action declares physical movement to another place."""
    return bool(_TRAVEL_RE.search(player_action or ""))


def infer_location_kind(location_id: str) -> tuple[str, str]:
    """Return (kind, danger) for a runtime location stub."""
    lower = normalize_place_id(location_id) or (location_id or "").strip().lower()
    if any(x in lower for x in ("locanda", "inn", "taverna", "osteria")):
        return "inn", "low"
    if any(x in lower for x in ("avamposto", "outpost", "fortino")):
        return "outpost", "medium"
    if any(x in lower for x in ("citta", "city", "villaggio", "piazza", "gilda")):
        return "settlement", "low"
    if any(x in lower for x in ("rovina", "rovine", "ruin", "cava", "tomba")):
        return "ruin", "high"
    if any(x in lower for x in ("strada", "road", "sentiero", "via")):
        return "road", "medium"
    if any(x in lower for x in ("bosco", "forest", "wilderness", "deserto")):
        return "wilderness", "high"
    return "default", "medium"
