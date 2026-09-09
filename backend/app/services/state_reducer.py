from __future__ import annotations

from app.models.game_state import CharacterRuntime, GameState, LocationRuntime
from app.models.reviews import CharacterPresentUpdate, LocationPresentUpdate, PresentReviewResult
from app.models.turn import FrontOutcome, SceneStateDelta, TurnResolution
from app.services.places import normalize_place_id
from app.services.presence import is_player_presence, without_player


def apply_scene_delta(state: GameState, delta: SceneStateDelta) -> None:
    """Apply a scene delta in place. Sole authority for scene mutations."""
    if not delta.preserve_scene_presence:
        if delta.player_location:
            loc = normalize_place_id(delta.player_location)
            if loc:
                state.player.location = loc
        if delta.characters_active is not None:
            state.characters_active = without_player(delta.characters_active, state.player)

    for character_id in delta.characters_add:
        cid = str(character_id or "").strip()
        if not cid or is_player_presence(cid, state.player):
            continue
        if cid not in state.characters_active:
            state.characters_active.append(cid)

    for character_id, update in delta.character_runtime.items():
        runtime = state.characters.setdefault(character_id, CharacterRuntime())
        if update.location:
            runtime.location = update.location
        if update.mood:
            runtime.mood = update.mood
        if update.relationship_delta is not None:
            runtime.relationship += update.relationship_delta
            runtime.relationship_delta = update.relationship_delta

    for location_id, update in delta.location_runtime.items():
        runtime = state.locations.setdefault(location_id, LocationRuntime())
        if update.objects:
            runtime.objects = list(dict.fromkeys(runtime.objects + update.objects))
        if update.atmosphere:
            runtime.atmosphere = update.atmosphere
        if update.events:
            runtime.events = list(dict.fromkeys(runtime.events + update.events))
            for event in update.events:
                if event not in state.situations:
                    state.situations.append(event)

    for item in delta.situations_add:
        if item not in state.situations:
            state.situations.append(item)
    for item in delta.situations_remove:
        if item in state.situations:
            state.situations.remove(item)

    for key, value in delta.extra_set.items():
        if key in {"session_id", "player", "characters", "locations", "situations"}:
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

    # front_impacts stay on the delta; caller applies via FrontEngine.apply_impacts


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
            )
        else:
            loc_updates[loc_id] = LocationPresentUpdate(atmosphere=atmosphere)

    char_runtime: dict[str, CharacterPresentUpdate] = {}
    for cid, loc in outcome.character_locations.items():
        char_runtime[cid] = CharacterPresentUpdate(location=loc)

    delta = SceneStateDelta(
        characters_add=list(outcome.characters_add),
        situations_add=list(outcome.situations_add),
        location_runtime=loc_updates,
        character_runtime=char_runtime,
    )
    apply_scene_delta(state, delta)
    return delta


def resolution_to_delta(resolution: TurnResolution) -> SceneStateDelta:
    """Map resolver output to a scene delta (location normalized)."""
    location = None
    if resolution.location:
        location = normalize_place_id(resolution.location) or None
    return SceneStateDelta(
        player_location=location,
        characters_active=list(resolution.present) if resolution.present is not None else None,
        situations_add=list(resolution.situations_add),
        situations_remove=list(resolution.situations_remove),
    )


def present_review_to_delta(
    result: PresentReviewResult,
    *,
    apply_presence: bool = True,
) -> SceneStateDelta:
    """Convert a present-review result into a SceneStateDelta."""
    player_location = None
    characters_active = None
    preserve = not apply_presence
    if apply_presence:
        if result.player_location:
            player_location = result.player_location
        characters_active = list(result.characters_active)

    return SceneStateDelta(
        player_location=player_location,
        characters_active=characters_active,
        situations_add=list(result.situations_add),
        situations_remove=list(result.situations_remove),
        character_runtime=dict(result.character_updates),
        location_runtime=dict(result.location_updates),
        front_impacts=list(result.front_impacts),
        extra_set=dict(result.extra_set),
        extra_remove=list(result.extra_remove),
        turns_present_reset=True,
        preserve_scene_presence=preserve,
    )
