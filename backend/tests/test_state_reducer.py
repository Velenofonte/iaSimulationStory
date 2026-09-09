"""Tests for SceneStateDelta / apply_scene_delta."""

from app.models import GameState, PlayerState
from app.models.reviews import CharacterPresentUpdate, FrontImpact, LocationPresentUpdate
from app.models.turn import FrontOutcome, SceneStateDelta, TurnResolution
from app.models.narrative import NarrativeTime
from app.services.state_reducer import (
    apply_front_outcome,
    apply_scene_delta,
    present_review_to_delta,
    resolution_to_delta,
)
from app.models.reviews import PresentReviewResult


def test_apply_scene_delta_location_and_present() -> None:
    state = GameState(session_id="s", player=PlayerState(location="e-rantel"))
    apply_scene_delta(
        state,
        SceneStateDelta(player_location="carne", characters_active=["enri"]),
    )
    assert state.player.location == "carne"
    assert state.characters_active == ["enri"]


def test_apply_scene_delta_does_not_apply_front_impacts() -> None:
    state = GameState(session_id="s", player=PlayerState(location="e-rantel"))
    state.fronts = {}
    delta = SceneStateDelta(
        front_impacts=[
            FrontImpact(
                front_id="missing",
                intent_id="x",
                effect="block",
            )
        ],
        situations_add=["filo aperto"],
    )
    apply_scene_delta(state, delta)
    assert "filo aperto" in state.situations
    # impacts left on delta for FrontEngine.apply_impacts
    assert len(delta.front_impacts) == 1


def test_resolution_to_delta() -> None:
    res = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        location="Carne",
        present=["enri", "enri"],
        situations_add=["La linea vacilla."],
        situations_remove=["La linea tiene."],
    )
    delta = resolution_to_delta(res)
    assert delta.player_location == "carne"
    assert delta.characters_active == ["enri"]
    assert delta.situations_add == ["La linea vacilla."]
    assert delta.situations_remove == ["La linea tiene."]


def test_apply_front_outcome_hydrates() -> None:
    state = GameState(session_id="s", player=PlayerState(location="village"))
    outcome = FrontOutcome(
        situations_add=["Rumore in piazza"],
        characters_add=["hero"],
        character_locations={"hero": "village"},
        location_events={"village": ["Rumore in piazza"]},
        location_atmosphere={"village": "Rumore"},
    )
    apply_front_outcome(state, outcome)
    assert "hero" in state.characters_active
    assert state.characters["hero"].location == "village"
    assert "Rumore in piazza" in state.situations


def test_present_review_to_delta_resets_counter() -> None:
    result = PresentReviewResult(
        characters_active=["enri"],
        situations_add=["a"],
        character_updates={"enri": CharacterPresentUpdate(mood="calma")},
        location_updates={"carne": LocationPresentUpdate(atmosphere="calma")},
    )
    delta = present_review_to_delta(result)
    assert delta.turns_present_reset is True
    assert delta.characters_active == ["enri"]
    assert delta.front_impacts == []


def test_apply_scene_delta_strips_player_from_present() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(name="Ainz", character_id="ainz", location="carne"),
        characters_active=["ainz", "enri"],
    )
    apply_scene_delta(
        state,
        SceneStateDelta(characters_active=["Ainz", "player", "enri", "gazef"]),
    )
    assert state.characters_active == ["enri", "gazef"]


def test_apply_scene_delta_scrubs_stale_player_when_presence_untouched() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(name="Hero", character_id="hero", location="carne"),
        characters_active=["hero", "enri"],
    )
    apply_scene_delta(state, SceneStateDelta(situations_add=["filo"]))
    assert state.characters_active == ["enri"]
    assert "filo" in state.situations


def test_characters_add_ignores_player() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(name="Rion", location="carne"),
    )
    apply_scene_delta(
        state,
        SceneStateDelta(characters_add=["rion", "enri", "Rion"]),
    )
    assert state.characters_active == ["enri"]
