"""Tests for the known_ids registry."""

from app.models import GameState, PlayerState
from app.models.game_state import CharacterRuntime, NpcKnowledgeFact
from app.services.id_registry import build_known_ids, situation_summaries


def test_build_known_ids_includes_offscreen_npc_knowledge() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(location="e-rantel"),
        characters_active=[],
        situations=[
            NpcKnowledgeFact(id="foresta_signore", summary="Messaggero all'avamposto")
        ],
        characters={
            "impiegato-gilda": CharacterRuntime(
                location="adventurers-guild",
                npc_knowledge=[
                    NpcKnowledgeFact(id="reclamo_kael", summary="Reclamo formalizzato"),
                ],
            )
        },
    )
    known = build_known_ids(state)
    assert known["situations"][0]["id"] == "foresta_signore"
    assert "impiegato-gilda" in known["npc_knowledge"]
    assert known["npc_knowledge"]["impiegato-gilda"][0]["id"] == "reclamo_kael"


def test_situation_summaries() -> None:
    state = GameState(
        session_id="s",
        situations=[NpcKnowledgeFact(id="a", summary="Filo A")],
    )
    assert situation_summaries(state) == ["Filo A"]
