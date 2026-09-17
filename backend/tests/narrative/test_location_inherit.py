"""location_scene_extra inherits atmosphere/ambient from parent places."""

from __future__ import annotations

from app.models.game_state import GameState, LocationRuntime, PlayerState
from app.narrative.narrative_context import NarrativeContextAssembler


def test_inherits_ambient_and_atmosphere_from_parent() -> None:
    asm = NarrativeContextAssembler()
    state = GameState(
        session_id="s1",
        player=PlayerState(name="Rayan", location="great-wall-south-trail"),
        locations={
            "great-wall": LocationRuntime(
                atmosphere="Il Grande Muro e' presidato.",
                ambient=["soldato di ronda", "arciere sul camminamento"],
                events=["Evento solo sul muro"],
            )
        },
    )
    extra = asm.location_scene_extra(state)
    assert extra["location_atmosphere"] == "Il Grande Muro e' presidato."
    assert "soldato di ronda" in extra["location_ambient"]
    assert "arciere sul camminamento" in extra["location_ambient"]
    # Events stay local — not inherited
    assert "location_events" not in extra


def test_child_overrides_parent_ambient() -> None:
    asm = NarrativeContextAssembler()
    state = GameState(
        session_id="s2",
        player=PlayerState(name="Rayan", location="great-wall-south-trail"),
        locations={
            "great-wall": LocationRuntime(
                atmosphere="Parent atm",
                ambient=["soldato di ronda"],
            ),
            "great-wall-south-trail": LocationRuntime(
                atmosphere="Tratto sud quieto",
                ambient=["vedetta isolata"],
            ),
        },
    )
    extra = asm.location_scene_extra(state)
    assert extra["location_atmosphere"] == "Tratto sud quieto"
    assert extra["location_ambient"] == ["vedetta isolata"]


def test_partial_inherit_atmosphere_only() -> None:
    asm = NarrativeContextAssembler()
    state = GameState(
        session_id="s3",
        player=PlayerState(name="Rayan", location="great-wall-south-trail"),
        locations={
            "great-wall": LocationRuntime(
                atmosphere="Parent atm",
                ambient=["soldato di ronda"],
            ),
            "great-wall-south-trail": LocationRuntime(
                ambient=["vedetta isolata"],
            ),
        },
    )
    extra = asm.location_scene_extra(state)
    assert extra["location_atmosphere"] == "Parent atm"
    assert extra["location_ambient"] == ["vedetta isolata"]
