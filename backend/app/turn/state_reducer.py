from __future__ import annotations

import re

from app.models.game_state import (
    CharacterRuntime,
    GameState,
    LocationRuntime,
    NpcKnowledgeFact,
    OffscreenCharacter,
)
from app.models.reviews import CharacterPresentUpdate, LocationPresentUpdate, PresentReviewResult
from app.models.turn import FrontOutcome, SceneStateDelta, TurnResolution
from app.player.knowledge import is_named, label, learn
from app.player.places import is_scene_departure_intent, normalize_place_id, player_at_place
from app.player.presence import is_player_presence, without_player


_FACT_MIN_TOKENS = 4
_FACT_OVERLAP = 0.6


PLAYER_FINDINGS_CAP = 12


def _fact_tokens(summary: str) -> set[str]:
    cleaned = re.sub(r"[^\w\s]", " ", (summary or "").casefold())
    return {t for t in cleaned.split() if len(t) > 3}


def _id_prefix_root(fid: str) -> str:
    """Strip accidental phase/variant suffixes (not intentional _start/_done)."""
    raw = (fid or "").strip().casefold()
    for suffix in (
        "_update",
        "_mattina",
        "_sera",
        "_attesa",
        "_sospeso",
        "_completo",
        "_complete",
        "_v2",
        "_v3",
        "_nuovo",
        "_new",
    ):
        if raw.endswith(suffix) and len(raw) > len(suffix) + 3:
            return raw[: -len(suffix)]
    return raw


def _duplicate_fact_id(facts: list[NpcKnowledgeFact], summary: str, *, new_id: str = "") -> str | None:
    """Id of an existing fact restating `summary` (or same thread prefix)."""
    if new_id:
        root = _id_prefix_root(new_id)
        for fact in facts:
            if _id_prefix_root(fact.id) == root and root:
                return fact.id
    tokens = _fact_tokens(summary)
    if len(tokens) < _FACT_MIN_TOKENS:
        return None
    for fact in facts:
        other = _fact_tokens(fact.summary)
        if len(other) < _FACT_MIN_TOKENS:
            continue
        if len(tokens & other) / min(len(tokens), len(other)) >= _FACT_OVERLAP:
            return fact.id
    return None


def _upsert_fact_list(
    existing: list[NpcKnowledgeFact],
    incoming: list[NpcKnowledgeFact],
) -> list[NpcKnowledgeFact]:
    """Merge facts by id; collapse fuzzy / prefix duplicates onto the older id."""
    by_id = {f.id: f for f in existing}
    for fact in incoming:
        fid = (fact.id or "").strip()
        summary = (fact.summary or "").strip()
        if not fid or not summary:
            continue
        if fid not in by_id:
            twin = _duplicate_fact_id(list(by_id.values()), summary, new_id=fid)
            if twin:
                fid = twin
        by_id[fid] = NpcKnowledgeFact(id=fid, summary=summary)
    return list(by_id.values())


def _remove_facts_by_id(
    existing: list[NpcKnowledgeFact],
    remove_ids: list[str],
) -> list[NpcKnowledgeFact]:
    """Drop facts whose id (or legacy summary string) matches remove_ids."""
    if not remove_ids:
        return list(existing)
    drop = {r.strip() for r in remove_ids if str(r or "").strip()}
    drop_cf = {r.casefold() for r in drop}
    out: list[NpcKnowledgeFact] = []
    for fact in existing:
        if fact.id in drop or fact.id.casefold() in drop_cf:
            continue
        if fact.summary in drop or fact.summary.casefold() in drop_cf:
            continue
        out.append(fact)
    return out


def apply_scene_delta(state: GameState, delta: SceneStateDelta) -> None:
    """Apply a scene delta in place. Sole authority for scene mutations."""
    location_changed = False
    previous_location = state.player.location
    if not delta.preserve_scene_presence:
        if delta.player_location:
            loc = normalize_place_id(delta.player_location)
            if loc:
                prev = normalize_place_id(state.player.location) or state.player.location
                if loc != prev:
                    location_changed = True
                state.player.location = loc

        if delta.characters_active is not None:
            state.characters_active = without_player(delta.characters_active, state.player)
            _sync_present_runtime_locations(state)
            # Anyone no longer in the full replacement leaves the cast silently;
            # explicit present_leave below can enrich offscreen entries.
            for cid in list(state.characters_offscreen):
                if cid in state.characters_active:
                    state.characters_offscreen.pop(cid, None)
        elif location_changed:
            # Location moved but present omitted → drop stale cast from the old place.
            state.characters_active = []

        if location_changed:
            _drop_offscreen_from_location(state, previous_location)

    # Arrivals: characters_add then present_join (same semantics).
    for character_id in list(delta.characters_add) + list(delta.present_join):
        cid = str(character_id or "").strip()
        if not cid or is_player_presence(cid, state.player):
            continue
        if cid not in state.characters_active:
            state.characters_active.append(cid)
        state.characters_offscreen.pop(cid, None)
        runtime = state.characters.setdefault(cid, CharacterRuntime())
        runtime.location = state.player.location

    # Departures win over arrivals/present membership.
    for character_id, entry in delta.present_leave.items():
        cid = str(character_id or "").strip()
        if not cid or is_player_presence(cid, state.player):
            continue
        if cid in state.characters_active:
            state.characters_active = [x for x in state.characters_active if x != cid]
        where = (entry.where or None) if entry else None
        reason = (entry.reason or None) if entry else None
        from_loc = (
            (entry.from_location if entry and entry.from_location else None)
            or state.player.location
        )
        state.characters_offscreen[cid] = OffscreenCharacter(
            where=where,
            reason=reason,
            from_location=from_loc,
        )
        runtime = state.characters.setdefault(cid, CharacterRuntime())
        if where:
            runtime.location = where

    for character_id, update in delta.character_runtime.items():
        runtime = state.characters.setdefault(character_id, CharacterRuntime())
        if update.location:
            runtime.location = update.location
        if update.mood:
            runtime.mood = update.mood
        if update.relationship_delta is not None:
            runtime.relationship += update.relationship_delta
            runtime.relationship_delta = update.relationship_delta

    for character_id, facts in delta.npc_knowledge_upsert.items():
        cid = str(character_id or "").strip()
        if not cid or is_player_presence(cid, state.player):
            continue
        runtime = state.characters.setdefault(cid, CharacterRuntime())
        runtime.npc_knowledge = _upsert_fact_list(list(runtime.npc_knowledge), list(facts))

    for location_id, update in delta.location_runtime.items():
        runtime = state.locations.setdefault(location_id, LocationRuntime())
        if update.objects:
            runtime.objects = list(dict.fromkeys(runtime.objects + update.objects))
        if update.atmosphere:
            runtime.atmosphere = update.atmosphere
        if getattr(update, "ambient", None):
            runtime.ambient = list(
                dict.fromkeys(list(runtime.ambient or []) + list(update.ambient))
            )
        if update.events:
            runtime.events = list(dict.fromkeys(runtime.events + update.events))
            # Location events open situation threads only when the PG is there
            # (offscreen front stamps keep place runtime without flooding situations).
            if player_at_place(state.player.location, location_id):
                from app.models.game_state import coerce_fact

                event_facts = [coerce_fact(e) for e in update.events]
                state.situations = _upsert_fact_list(
                    list(state.situations),
                    [f for f in event_facts if f is not None],
                )

    if delta.situations_add or delta.situations_remove:
        merged = _upsert_fact_list(list(state.situations), list(delta.situations_add or []))
        state.situations = _remove_facts_by_id(merged, list(delta.situations_remove or []))

    if delta.player_findings_add or delta.player_findings_remove:
        merged = _upsert_fact_list(
            list(state.player_findings), list(delta.player_findings_add or [])
        )
        trimmed = _remove_facts_by_id(
            merged, list(delta.player_findings_remove or [])
        )
        if len(trimmed) > PLAYER_FINDINGS_CAP:
            trimmed = trimmed[-PLAYER_FINDINGS_CAP:]
        state.player_findings = trimmed

    for key, value in delta.extra_set.items():
        if key in {
            "session_id",
            "player",
            "characters",
            "locations",
            "situations",
            "player_findings",
        }:
            continue
        state.extra[key] = value
    for key in delta.extra_remove:
        state.extra.pop(key, None)

    if delta.party_active is not None:
        state.party_active = delta.party_active

    if delta.turns_present_reset:
        state.turns_since_present_review = 0
    if delta.turns_consolidation_reset:
        state.turns_since_consolidation = 0

    # PG is never an "active NPC"; scrub even when presence was not replaced this turn.
    state.characters_active = without_player(state.characters_active, state.player)
    for cid in list(state.characters_offscreen):
        if is_player_presence(cid, state.player):
            state.characters_offscreen.pop(cid, None)

    # front_impacts stay on the delta; caller applies via FrontEngine.apply_impacts


def _sync_present_runtime_locations(state: GameState) -> None:
    """Mark everyone currently with the PG as being at the player's location."""
    loc = state.player.location
    for cid in state.characters_active:
        runtime = state.characters.setdefault(cid, CharacterRuntime())
        runtime.location = loc


def _drop_offscreen_from_location(state: GameState, left_location: str | None) -> None:
    """Drop offscreen entries tied to the place the PG just left."""
    left = normalize_place_id(left_location or "") or (left_location or "")
    if not left:
        return
    for cid, entry in list(state.characters_offscreen.items()):
        from_loc = normalize_place_id(entry.from_location or "") or (entry.from_location or "")
        if from_loc and from_loc == left:
            state.characters_offscreen.pop(cid, None)


def resolve_presence_for_location_change(
    *,
    previous_location: str | None,
    new_location: str | None,
    present: list[str] | None,
    departing: bool = False,
) -> list[str] | None:
    """When the PG moves or leaves the cast behind, present must be re-evaluated.

    - present provided → use it (full replacement)
    - present omitted + (location changed OR departing) → [] (fail-closed)
    - otherwise → present unchanged (None = no-touch)
    """
    if present is not None:
        return list(present)
    prev = normalize_place_id(previous_location or "") or (previous_location or "")
    nxt = normalize_place_id(new_location or "") or (new_location or "")
    location_changed = bool(nxt and nxt != prev)
    if location_changed or departing:
        return []
    return None


def apply_front_outcome(state: GameState, outcome: FrontOutcome) -> SceneStateDelta:
    """Convert front outcome to a delta, apply it, and return the delta."""
    loc_updates: dict[str, LocationPresentUpdate] = {}
    for loc_id, events in outcome.location_events.items():
        loc_updates[loc_id] = LocationPresentUpdate(events=list(events))
    for loc_id, atmosphere in outcome.location_atmosphere.items():
        existing = loc_updates.get(loc_id)
        if existing:
            loc_updates[loc_id] = LocationPresentUpdate(
                events=list(existing.events),
                atmosphere=atmosphere,
                objects=list(existing.objects),
                ambient=list(existing.ambient),
            )
        else:
            loc_updates[loc_id] = LocationPresentUpdate(atmosphere=atmosphere)
    for loc_id, roles in (outcome.location_ambient or {}).items():
        existing = loc_updates.get(loc_id)
        if existing:
            loc_updates[loc_id] = LocationPresentUpdate(
                events=list(existing.events),
                atmosphere=existing.atmosphere,
                objects=list(existing.objects),
                ambient=list(dict.fromkeys(list(existing.ambient) + list(roles))),
            )
        else:
            loc_updates[loc_id] = LocationPresentUpdate(ambient=list(roles))

    char_runtime: dict[str, CharacterPresentUpdate] = {}
    for cid, loc in outcome.character_locations.items():
        char_runtime[cid] = CharacterPresentUpdate(location=loc)

    present_leave: dict[str, OffscreenCharacter] = {}
    for cid, place in (outcome.characters_nearby or {}).items():
        if cid in outcome.characters_add:
            continue
        present_leave[cid] = OffscreenCharacter(
            where=place,
            reason="nearby sul luogo (non interlocutore finche' non cercato)",
        )

    delta = SceneStateDelta(
        characters_add=list(outcome.characters_add),
        present_leave=present_leave,
        situations_add=list(outcome.situations_add),
        location_runtime=loc_updates,
        character_runtime=char_runtime,
    )
    apply_scene_delta(state, delta)

    for cid in outcome.characters_add:
        learn(state, cid, "named")
    return delta


def projected_acting_cast(
    *,
    previous_present: list[str],
    present: list[str] | None,
    present_join: list[str],
    present_leave: dict[str, OffscreenCharacter] | None,
) -> set[str]:
    """NPC ids allowed to act / receive knowledge after this resolution."""
    if present is not None:
        cast = [str(x).strip() for x in present if str(x or "").strip()]
    else:
        cast = [str(x).strip() for x in previous_present if str(x or "").strip()]
    seen = {c.casefold() for c in cast}
    for raw in present_join:
        token = str(raw or "").strip()
        if token and token.casefold() not in seen:
            cast.append(token)
            seen.add(token.casefold())
    leave = {str(k).strip().casefold() for k in (present_leave or {})}
    return {c for c in cast if c.casefold() not in leave}


def _filter_knowledge_to_cast(
    upsert: dict[str, list[NpcKnowledgeFact]],
    allowed: set[str],
) -> dict[str, list[NpcKnowledgeFact]]:
    allowed_cf = {a.casefold() for a in allowed}
    return {
        cid: facts
        for cid, facts in (upsert or {}).items()
        if str(cid).strip().casefold() in allowed_cf
    }


def filter_findings_leak(
    state: GameState,
    upsert: dict[str, list[NpcKnowledgeFact]],
    revealed: list[str] | None = None,
    *,
    extra_private: list[NpcKnowledgeFact] | None = None,
) -> dict[str, list[NpcKnowledgeFact]]:
    """Drop npc_knowledge facts that leak unrevealed player_findings ids."""
    private_ids = {
        (f.id or "").strip().casefold()
        for f in list(state.player_findings or []) + list(extra_private or [])
        if (f.id or "").strip()
    }
    if not private_ids:
        return upsert
    revealed_cf = {
        str(x).strip().casefold()
        for x in (revealed or [])
        if str(x).strip()
    }
    out: dict[str, list[NpcKnowledgeFact]] = {}
    for cid, facts in (upsert or {}).items():
        kept: list[NpcKnowledgeFact] = []
        for f in facts:
            fid = (f.id or "").strip().casefold()
            if fid and fid in private_ids and fid not in revealed_cf:
                continue
            kept.append(f)
        if kept:
            out[cid] = kept
    return out


def resolution_to_delta(
    resolution: TurnResolution,
    *,
    previous_location: str | None = None,
    previous_present: list[str] | None = None,
    state: GameState | None = None,
    player_action: str = "",
    departing: bool | None = None,
) -> SceneStateDelta:
    """Map resolver output to a scene delta (location normalized)."""
    location = None
    if resolution.location:
        location = normalize_place_id(resolution.location) or None
    prev_norm = normalize_place_id(previous_location or "") or (previous_location or "")
    loc_changed = bool(location and location != prev_norm)
    if departing is None:
        departing = is_scene_departure_intent(
            player_action,
            location_changed=loc_changed,
        )
    present = resolve_presence_for_location_change(
        previous_location=previous_location,
        new_location=location,
        present=resolution.present,
        departing=bool(departing),
    )
    knowledge = dict(resolution.npc_knowledge_upsert)
    if previous_present is not None:
        allowed = projected_acting_cast(
            previous_present=previous_present,
            present=present,
            present_join=list(resolution.present_join),
            present_leave=dict(resolution.present_leave),
        )
        knowledge = _filter_knowledge_to_cast(knowledge, allowed)
    if state is not None or resolution.player_findings_add:
        probe = state if state is not None else GameState(session_id="_probe")
        knowledge = filter_findings_leak(
            probe,
            knowledge,
            list(resolution.player_findings_reveal),
            extra_private=list(resolution.player_findings_add),
        )
    return SceneStateDelta(
        player_location=location,
        characters_active=present,
        present_join=list(resolution.present_join),
        present_leave=dict(resolution.present_leave),
        situations_add=list(resolution.situations_add),
        situations_remove=list(resolution.situations_remove),
        player_findings_add=list(resolution.player_findings_add),
        player_findings_remove=[],
        npc_knowledge_upsert=knowledge,
    )


def filter_npc_knowledge_upsert(
    state: GameState,
    upsert: dict[str, list[NpcKnowledgeFact]],
) -> dict[str, list[NpcKnowledgeFact]]:
    """Present-review: keep new facts and updates to existing ids; drop no-ops."""
    out: dict[str, list[NpcKnowledgeFact]] = {}
    for cid, facts in upsert.items():
        runtime = state.characters.get(cid)
        known = list(runtime.npc_knowledge) if runtime else []
        by_id = {f.id: f for f in known}
        fresh: list[NpcKnowledgeFact] = []
        for f in facts:
            fid = (f.id or "").strip()
            summary = (f.summary or "").strip()
            if not fid or not summary:
                continue
            if fid in by_id:
                if by_id[fid].summary.strip() == summary:
                    continue  # no-op
                fresh.append(NpcKnowledgeFact(id=fid, summary=summary))
                continue
            twin = _duplicate_fact_id(known, summary, new_id=fid)
            if twin:
                if by_id[twin].summary.strip() == summary:
                    continue
                fresh.append(NpcKnowledgeFact(id=twin, summary=summary))
                continue
            fresh.append(NpcKnowledgeFact(id=fid, summary=summary))
        if fresh:
            out[cid] = fresh
    return out


# Back-compat alias used by older tests / imports.
filter_npc_knowledge_add_only = filter_npc_knowledge_upsert


def format_offscreen_lines(
    state: GameState,
    *,
    roles: dict[str, str] | None = None,
) -> list[str]:
    """Human-readable offscreen cast for canon_facts / LLM context.

    Unknown names are masked via the PC lens (role + NARRATOR_ONLY id).
    """
    role_map = {str(k).lower(): v for k, v in (roles or {}).items()}
    lines: list[str] = []
    for cid, entry in state.characters_offscreen.items():
        role = role_map.get(str(cid).lower())
        if is_named(state, cid):
            head = cid
        else:
            head = label(state, cid, role)
        parts = [head]
        if entry.where:
            parts.append(entry.where)
        if entry.reason:
            parts.append(entry.reason)
        if len(parts) == 1:
            lines.append(head)
        elif len(parts) == 2:
            lines.append(f"{head} — {parts[1]}")
        else:
            lines.append(f"{head} — {parts[1]}: {parts[2]}")
    return lines


def present_review_to_delta(
    result: PresentReviewResult,
    *,
    apply_presence: bool = True,
    state: GameState | None = None,
) -> SceneStateDelta:
    """Convert a present-review result into a SceneStateDelta."""
    player_location = None
    characters_active = None
    present_leave: dict[str, OffscreenCharacter] = {}
    preserve = not apply_presence
    if apply_presence:
        if result.player_location:
            player_location = normalize_place_id(result.player_location) or result.player_location
        characters_active = list(result.characters_active)
        # Explicit leave from review, if any.
        explicit = getattr(result, "present_leave", None) or {}
        if isinstance(explicit, dict):
            present_leave.update(explicit)
        # Anyone dropped from the cast without an explicit leave becomes offscreen.
        if state is not None:
            kept = set(without_player(characters_active or [], state.player))
            for cid in state.characters_active:
                if cid in kept or cid in present_leave:
                    continue
                if is_player_presence(cid, state.player):
                    continue
                present_leave[cid] = OffscreenCharacter(
                    reason="non piu' in scena (present review)",
                    from_location=state.player.location,
                )

    knowledge = dict(getattr(result, "npc_knowledge_upsert", None) or {})
    if state is not None and knowledge:
        knowledge = filter_npc_knowledge_upsert(state, knowledge)
        knowledge = filter_findings_leak(state, knowledge, revealed=[])

    return SceneStateDelta(
        player_location=player_location,
        characters_active=characters_active,
        present_leave=present_leave,
        situations_add=list(result.situations_add),
        situations_remove=list(result.situations_remove),
        character_runtime=dict(result.character_updates),
        location_runtime=dict(result.location_updates),
        front_impacts=list(result.front_impacts),
        extra_set=dict(result.extra_set),
        extra_remove=list(result.extra_remove),
        turns_present_reset=True,
        preserve_scene_presence=preserve,
        npc_knowledge_upsert=knowledge,
    )
