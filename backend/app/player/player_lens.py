"""Player-character epistemic lens: what the PC has learned in play.

Outbound gate only — the engine must not spontaneously name people/places
the PC has not encountered. If the player meta-games a name into the message,
the world responds normally and the lens records it.
"""

from __future__ import annotations

import re
from app.models.game_state import GameState, LensLevel, PlayerLens
from app.player.places import normalize_place_id

_WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_KNOWLEDGE_SECTION_RE = re.compile(
    r"(?im)^#\s*Knowledge scope\s*\n(.*?)(?=^#\s|\Z)",
    re.DOTALL,
)

_LEVEL_RANK: dict[LensLevel, int] = {"seen": 1, "named": 2}


def _norm_id(entity_id: str | None) -> str:
    return str(entity_id or "").strip().lower()


def ensure_lens(state: GameState) -> PlayerLens:
    if state.player.lens is None:
        state.player.lens = PlayerLens()
    return state.player.lens


def level(state: GameState, entity_id: str | None) -> LensLevel | None:
    eid = _norm_id(entity_id)
    if not eid:
        return None
    return ensure_lens(state).entities.get(eid)


def knows(state: GameState, entity_id: str | None) -> bool:
    return level(state, entity_id) is not None


def is_named(state: GameState, entity_id: str | None) -> bool:
    return level(state, entity_id) == "named"


def known_ids(state: GameState, *, min_level: LensLevel = "seen") -> list[str]:
    rank = _LEVEL_RANK[min_level]
    out: list[str] = []
    for eid, lv in ensure_lens(state).entities.items():
        if _LEVEL_RANK.get(lv, 0) >= rank:
            out.append(eid)
    return sorted(out)


def learn(state: GameState, entity_id: str | None, depth: LensLevel) -> bool:
    """Raise lens depth for entity_id. Returns True if state changed."""
    eid = _norm_id(entity_id)
    if not eid:
        return False
    lens = ensure_lens(state)
    current = lens.entities.get(eid)
    if current is not None and _LEVEL_RANK[current] >= _LEVEL_RANK[depth]:
        return False
    lens.entities[eid] = depth
    return True


def place_and_parent(location: str | None) -> list[str]:
    """Location id plus its parent path segment (e.g. e-rantel/tavern → both)."""
    loc = normalize_place_id(location) or (location or "").strip().lower()
    if not loc:
        return []
    ids = [loc]
    if "/" in loc:
        parent = loc.rsplit("/", 1)[0].strip()
        if parent and parent not in ids:
            ids.append(parent)
    leaf = loc.split("/")[-1]
    if leaf and leaf not in ids:
        ids.append(leaf)
    return ids


def label(
    state: GameState,
    entity_id: str | None,
    role: str | None = None,
) -> str:
    """Prompt-facing label: proper id if named, else role + NARRATOR_ONLY id."""
    eid = _norm_id(entity_id)
    role_txt = (role or "").strip() or "figura"
    if not eid:
        return role_txt
    if is_named(state, eid):
        return f"{eid} ({role_txt})" if role_txt and role_txt != "figura" else eid
    return f"{role_txt} (id: {eid}, NARRATOR_ONLY)"


def message_has_speech(message: str | None) -> bool:
    """True if the player used spoken dialogue markers this turn."""
    text = message or ""
    return any(mark in text for mark in ('"', "«", "»", "“", "”"))


def learn_from_message_tokens(
    state: GameState,
    tokens: list[str] | set[str],
) -> list[str]:
    """Mark capitalized / extracted tokens the player used as named."""
    learned: list[str] = []
    for raw in tokens:
        eid = _norm_id(raw)
        if not eid:
            continue
        if learn(state, eid, "named"):
            learned.append(eid)
    return learned


def apply_turn_learning(
    state: GameState,
    *,
    message: str | None = None,
    previous_location: str | None = None,
    message_entity_ids: list[str] | None = None,
    front_introduced: list[str] | None = None,
) -> None:
    """Deterministic lens updates after a scene delta / front tick."""
    loc = state.player.location
    prev = normalize_place_id(previous_location) or (previous_location or "")
    cur = normalize_place_id(loc) or (loc or "")
    if cur and cur != prev:
        for place_id in place_and_parent(cur):
            learn(state, place_id, "named")
    elif cur and not level(state, cur):
        # First seed / ensure current place is known
        for place_id in place_and_parent(cur):
            learn(state, place_id, "named")

    for cid in list(state.characters_active):
        learn(state, cid, "seen")

    for cid in front_introduced or []:
        learn(state, cid, "named")

    if message_has_speech(message):
        for cid in list(state.characters_active):
            learn(state, cid, "named")

    if message_entity_ids:
        learn_from_message_tokens(state, message_entity_ids)

    # Also: present/offscreen ids explicitly typed in the message (any case)
    msg_cf = (message or "").casefold()
    if msg_cf:
        candidates = set(state.characters_active) | set(state.characters_offscreen)
        if state.party_active:
            candidates.add(state.party_active)
        for cid in candidates:
            token = _norm_id(cid)
            if token and token in msg_cf:
                learn(state, cid, "named")


def extract_knowledge_scope_links(body: str) -> list[str]:
    """Wiki ids linked from the Knowledge scope H1 section of a sheet."""
    if not body:
        return []
    match = _KNOWLEDGE_SECTION_RE.search(body)
    section = match.group(1) if match else body
    return [_norm_id(m) for m in _WIKI_LINK_RE.findall(section) if _norm_id(m)]


def seed_player_lens(
    state: GameState,
    *,
    sheet_body: str | None = None,
    sheet_meta: dict | None = None,
) -> None:
    """Bootstrap lens at session/era start from location, party, sheet knowledge."""
    for place_id in place_and_parent(state.player.location):
        learn(state, place_id, "named")

    self_id = state.player.resolved_character_id()
    if self_id:
        learn(state, self_id, "named")

    if state.party_active:
        learn(state, state.party_active, "named")
    if state.player.party_id:
        learn(state, state.player.party_id, "named")

    meta = sheet_meta or {}
    for key in ("residence", "affiliation", "origin_place", "home"):
        raw = meta.get(key)
        if raw is None:
            continue
        text = str(raw)
        for link in _WIKI_LINK_RE.findall(text):
            learn(state, link, "named")
        # bare id (no brackets)
        bare = _norm_id(text.replace("_", "-"))
        if bare and " " not in bare and "[[" not in text:
            learn(state, bare, "named")

    for link in extract_knowledge_scope_links(sheet_body or ""):
        learn(state, link, "named")


def backfill_from_chat(
    state: GameState,
    chat_texts: list[str],
    *,
    candidate_ids: list[str] | None = None,
) -> list[str]:
    """Mark as named any candidate id whose token appears in prior chat."""
    blob = "\n".join(chat_texts or []).casefold()
    if not blob:
        return []
    candidates = list(candidate_ids or [])
    if not candidates:
        candidates = (
            list(state.characters_active)
            + list(state.characters_offscreen)
            + known_ids(state)
        )
    learned: list[str] = []
    for cid in candidates:
        token = _norm_id(cid)
        if not token:
            continue
        if token in blob and learn(state, cid, "named"):
            learned.append(cid)
    return learned
