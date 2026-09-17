"""Player assets and story views: sheet, spellbook, timeline, chronicle."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import deps
from app.api.deps import require_session
from app.api.schemas import (
    CharacterSheet,
    SpellEntry,
    SpellbookResponse,
    SpellbookTagsRequest,
    StoryViewResponse,
)
from app.models.game_state import ArcTimelineResponse
from app.story.era_loader import EraLoader
from app.story.story_engine import filter_chronicle_for_player, player_is_insider

router = APIRouter(tags=["player_assets"])


@router.get("/session/{session_id}/story", response_model=StoryViewResponse)
def get_session_story(session_id: str) -> StoryViewResponse:
    state, svc = require_session(session_id)
    era = None
    try:
        if state.story.era:
            era = EraLoader(story_id=state.story_id).load(state.story.era)
    except (FileNotFoundError, ValueError):
        era = None
    is_insider = player_is_insider(state, era)
    visible = filter_chronicle_for_player(
        list(state.story.chronicle),
        is_insider=is_insider,
        min_reach="local",
    )
    return StoryViewResponse(
        era=state.story.era,
        current_arc=state.story.current_arc,
        chronicle=[e.model_dump() for e in visible],
        arcs=[a.model_dump() for a in state.story.arcs],
        pressures=[p.model_dump() for p in state.story.pressures],
        world_flags=dict(state.story.world_flags),
        next_candidates=svc.story.next_candidates(state),
    )


@router.get("/session/{session_id}/sheet", response_model=CharacterSheet)
def get_player_sheet(session_id: str) -> CharacterSheet:
    state, svc = require_session(session_id)
    pid = state.player.resolved_character_id()
    svc.wiki.ensure_player(state.player.name, state.player.location, character_id=pid)
    data = svc.wiki.read_character(pid)
    return CharacterSheet.model_validate(data)


@router.get("/session/{session_id}/spellbook", response_model=SpellbookResponse)
def get_spellbook(session_id: str) -> SpellbookResponse:
    state, svc = require_session(session_id)
    pid = state.player.resolved_character_id()
    spells = svc.wiki.read_spellbook(state.player.name, character_id=pid)
    return SpellbookResponse(
        player_id=pid,
        spells=[SpellEntry.model_validate(s) for s in spells],
    )


@router.post("/session/{session_id}/spellbook/tags", response_model=SpellbookResponse)
def update_spellbook_tags(
    session_id: str, payload: SpellbookTagsRequest
) -> SpellbookResponse:
    state, svc = require_session(session_id)
    pid = state.player.resolved_character_id()
    updates = [u.model_dump() for u in payload.updates]
    spells = svc.wiki.set_spell_tags(
        pid, updates, player_name=state.player.name
    )
    return SpellbookResponse(
        player_id=pid,
        spells=[SpellEntry.model_validate(s) for s in spells],
    )


@router.get("/session/{session_id}/arc-timeline", response_model=ArcTimelineResponse)
def get_arc_timeline(session_id: str) -> ArcTimelineResponse:
    state, svc = require_session(session_id)
    fired = svc.fronts.sync_to_clock(state, for_display=True)
    if fired:
        deps.saves.save_game_state(state)
    return svc.fronts.build_canon_timeline(state)
