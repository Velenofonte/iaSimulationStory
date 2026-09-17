"""Player findings channel + npc_knowledge firewall."""

from __future__ import annotations

from app.models.game_state import GameState, NpcKnowledgeFact
from app.models.narrative import NarrativeTime
from app.models.turn import TurnResolution
from app.turn.state_reducer import (
    PLAYER_FINDINGS_CAP,
    apply_scene_delta,
    filter_findings_leak,
    resolution_to_delta,
)


def _state() -> GameState:
    return GameState(session_id="s1", story_id="overlord")


def test_findings_persist_via_delta() -> None:
    state = _state()
    resolution = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        player_findings_add=[
            NpcKnowledgeFact(id="aura_gate", summary="Aura intensa oltre il muro")
        ],
    )
    apply_scene_delta(state, resolution_to_delta(resolution, state=state))
    assert len(state.player_findings) == 1
    assert state.player_findings[0].id == "aura_gate"


def test_findings_cap_drops_oldest() -> None:
    state = _state()
    state.player_findings = [
        NpcKnowledgeFact(id=f"f{i}", summary=f"fact {i}")
        for i in range(PLAYER_FINDINGS_CAP)
    ]
    resolution = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=1),
        player_findings_add=[
            NpcKnowledgeFact(id="newest", summary="ultimo finding")
        ],
    )
    apply_scene_delta(state, resolution_to_delta(resolution, state=state))
    assert len(state.player_findings) == PLAYER_FINDINGS_CAP
    assert state.player_findings[-1].id == "newest"
    assert state.player_findings[0].id == "f1"


def test_filter_blocks_unrevealed_finding() -> None:
    state = _state()
    state.player_findings = [
        NpcKnowledgeFact(id="aura_gate", summary="Aura intensa")
    ]
    upsert = {
        "vex": [NpcKnowledgeFact(id="aura_gate", summary="Aura intensa")]
    }
    blocked = filter_findings_leak(state, upsert, revealed=[])
    assert "vex" not in blocked

    allowed = filter_findings_leak(state, upsert, revealed=["aura_gate"])
    assert allowed["vex"][0].id == "aura_gate"


def test_resolution_to_delta_blocks_same_turn_finding_leak() -> None:
    state = _state()
    resolution = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        present=["vex"],
        player_findings_add=[
            NpcKnowledgeFact(id="secret_read", summary="Fonte di potere sotto la breccia")
        ],
        npc_knowledge_upsert={
            "vex": [
                NpcKnowledgeFact(
                    id="secret_read",
                    summary="Fonte di potere sotto la breccia",
                )
            ]
        },
    )
    delta = resolution_to_delta(
        resolution,
        previous_present=["vex"],
        state=state,
    )
    assert "vex" not in delta.npc_knowledge_upsert
    assert delta.player_findings_add[0].id == "secret_read"
