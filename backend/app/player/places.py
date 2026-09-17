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
    # Holy Kingdom
    "hoburns": "hoburns",
    "capitale-del-santo-regno": "hoburns",
    "kalinsha": "kalinsha",
    "great-wall": "great-wall",
    "grande-muro": "great-wall",
    "il grande muro": "great-wall",
    "abelion-hills": "abelion-hills",
    "colline-abelion": "abelion-hills",
    "abelion hills": "abelion-hills",
    "re-estize": "re-estize",
    "re estize": "re-estize",
    "liberation-camp": "liberation-camp",
    "campo-liberazione": "liberation-camp",
    "prison-camp": "prison-camp",
    "loyts": "loyts",
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

# Movement along / away within the same place id (road, walkway, long room).
# Kept separate from travel so location-required retries do not fire.
_ALONG_MOVE_RE = re.compile(
    r"(?:"
    r"\b(?:corro|corriamo|cammino|camminiamo|avanzo|avanziamo)\b"
    r"|mi\s+allontano"
    r"|continuo\s+(?:\S+\s+){0,8}?(?:verso|lungo|fino)"
    r"|seguo\s+(?:il|la|lo|i|le|gli)\b"
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


def is_subplace(child: str, parent: str) -> bool:
    """True when child id is a hyphen-prefixed sub-place of parent (after normalize)."""
    c = normalize_place_id(child)
    p = normalize_place_id(parent)
    if not c or not p or c == p:
        return False
    return c.startswith(p + "-")


def place_ancestors(location_id: str) -> list[str]:
    """Hyphen prefix chain from nearest parent to root (excludes self).

    ``great-wall-south-trail`` → ``["great-wall-south", "great-wall"]``.
    """
    loc = normalize_place_id(location_id)
    if not loc or "-" not in loc:
        return []
    parts = loc.split("-")
    out: list[str] = []
    for i in range(len(parts) - 1, 0, -1):
        out.append("-".join(parts[:i]))
    return out


def player_at_place(player_location: str, place: str) -> bool:
    """True when player location and beat place refer to the same site or sub-place."""
    a = normalize_place_id(player_location)
    b = normalize_place_id(place)
    if not a or not b:
        return False
    if a == b:
        return True
    return is_subplace(a, b) or is_subplace(b, a)


def is_travel_intent(player_action: str) -> bool:
    """True when the player action declares physical movement to another place."""
    return bool(_TRAVEL_RE.search(player_action or ""))


def is_along_move_intent(player_action: str) -> bool:
    """True when the PG moves along/away without necessarily changing place id."""
    return bool(_ALONG_MOVE_RE.search(player_action or ""))


def is_scene_departure_intent(
    player_action: str,
    *,
    location_changed: bool,
) -> bool:
    """True when cast must be re-evaluated (new place or along-move / travel)."""
    if location_changed:
        return True
    return is_travel_intent(player_action) or is_along_move_intent(player_action)


def infer_location_kind(location_id: str) -> tuple[str, str]:
    """Return (kind, danger) for a runtime location stub."""
    lower = normalize_place_id(location_id) or (location_id or "").strip().lower()
    if any(x in lower for x in ("locanda", "inn", "taverna", "osteria")):
        return "inn", "low"
    if any(
        x in lower
        for x in (
            "great-wall",
            "grande-muro",
            "muro",
            "wall",
            "fortezza",
            "fortress",
            "bastione",
            "guarnigione",
            "garrison",
        )
    ):
        return "fortress", "high"
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
