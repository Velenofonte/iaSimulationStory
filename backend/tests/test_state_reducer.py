"""Tests for SceneStateDelta / apply_scene_delta."""

from app.models import GameState, PlayerState
from app.models.game_state import NpcKnowledgeFact
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


def test_npc_knowledge_collapses_restated_fact() -> None:
    state = GameState(session_id="s", player=PlayerState(location="bosco"))
    apply_scene_delta(
        state,
        SceneStateDelta(
            npc_knowledge_upsert={
                "harn": [
                    NpcKnowledgeFact(
                        id="naga_killed",
                        summary="Rayan ha ucciso una naga con un dardo di fuoco in un istante.",
                    )
                ]
            }
        ),
    )
    apply_scene_delta(
        state,
        SceneStateDelta(
            npc_knowledge_upsert={
                "harn": [
                    NpcKnowledgeFact(
                        id="naga_uccisa",
                        summary="Rayan ha ucciso la naga con un dardo di fuoco fulmineo.",
                    )
                ]
            }
        ),
    )
    facts = state.characters["harn"].npc_knowledge
    assert len(facts) == 1
    assert facts[0].id == "naga_killed"
    assert "fulmineo" in facts[0].summary


def test_npc_knowledge_keeps_distinct_facts() -> None:
    state = GameState(session_id="s", player=PlayerState(location="bosco"))
    apply_scene_delta(
        state,
        SceneStateDelta(
            npc_knowledge_upsert={
                "harn": [
                    NpcKnowledgeFact(
                        id="naga_killed",
                        summary="Rayan ha ucciso una naga con un dardo di fuoco in un istante.",
                    ),
                    NpcKnowledgeFact(
                        id="carico_consegnato",
                        summary="Il carico di attrezzi da fabbro e' stato lasciato all'avamposto.",
                    ),
                ]
            }
        ),
    )
    assert len(state.characters["harn"].npc_knowledge) == 2


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
    assert any(s.summary == "filo aperto" for s in state.situations)
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
    assert len(delta.situations_add) == 1
    assert delta.situations_add[0].summary == "La linea vacilla."
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
    assert any(s.summary == "Rumore in piazza" for s in state.situations)


def test_situations_upsert_by_id() -> None:
    state = GameState(session_id="s", player=PlayerState(location="e-rantel"))
    apply_scene_delta(
        state,
        SceneStateDelta(
            situations_add=[
                NpcKnowledgeFact(id="reclamo_kael", summary="Kael non si e' presentato"),
            ]
        ),
    )
    apply_scene_delta(
        state,
        SceneStateDelta(
            situations_add=[
                NpcKnowledgeFact(
                    id="reclamo_kael",
                    summary="Rayan ha formalizzato il reclamo per Kael",
                )
            ]
        ),
    )
    assert len(state.situations) == 1
    assert state.situations[0].id == "reclamo_kael"
    assert "formalizzato" in state.situations[0].summary


def test_situations_remove_by_id() -> None:
    state = GameState(session_id="s", player=PlayerState(location="e-rantel"))
    apply_scene_delta(
        state,
        SceneStateDelta(
            situations_add=[
                NpcKnowledgeFact(id="foresta_signore", summary="Messaggero muto all'avamposto"),
            ]
        ),
    )
    apply_scene_delta(
        state,
        SceneStateDelta(situations_remove=["foresta_signore"]),
    )
    assert state.situations == []


def test_situations_legacy_string_migration() -> None:
    state = GameState.model_validate(
        {
            "session_id": "s",
            "situations": ["Testo libero senza id"],
        }
    )
    assert len(state.situations) == 1
    assert state.situations[0].summary == "Testo libero senza id"
    assert state.situations[0].id


def test_npc_knowledge_prefix_collapse() -> None:
    state = GameState(session_id="s", player=PlayerState(location="gilda"))
    apply_scene_delta(
        state,
        SceneStateDelta(
            npc_knowledge_upsert={
                "impiegato": [
                    NpcKnowledgeFact(
                        id="reclamo_kael",
                        summary="Kael non si e' presentato all'alba per i lupi",
                    )
                ]
            }
        ),
    )
    apply_scene_delta(
        state,
        SceneStateDelta(
            npc_knowledge_upsert={
                "impiegato": [
                    NpcKnowledgeFact(
                        id="reclamo_kael_mattina",
                        summary="Rayan formalizza il reclamo per assenza di Kael alla missione lupi",
                    )
                ]
            }
        ),
    )
    facts = state.characters["impiegato"].npc_knowledge
    assert len(facts) == 1
    assert facts[0].id == "reclamo_kael"
    assert "formalizza" in facts[0].summary


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
    assert any(s.summary == "filo" for s in state.situations)


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


def test_location_change_without_present_clears_stale_cast() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(location="nfirea-lizzy-shop"),
        characters_active=["nfirea", "nfirea_bareare"],
    )
    apply_scene_delta(
        state,
        SceneStateDelta(player_location="boar-inn"),
    )
    assert state.player.location == "boar-inn"
    assert state.characters_active == []


def test_location_change_with_present_replaces_cast() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(location="nfirea-lizzy-shop"),
        characters_active=["nfirea"],
    )
    apply_scene_delta(
        state,
        SceneStateDelta(
            player_location="boar-inn",
            characters_active=["oste"],
        ),
    )
    assert state.characters_active == ["oste"]
    assert state.characters["oste"].location == "boar-inn"


def test_same_location_without_present_keeps_cast() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(location="boar-inn"),
        characters_active=["oste"],
    )
    apply_scene_delta(
        state,
        SceneStateDelta(player_location="boar-inn", situations_add=["camera presa"]),
    )
    assert state.characters_active == ["oste"]
    assert any(s.summary == "camera presa" for s in state.situations)


def test_resolution_to_delta_clears_present_on_move_when_omitted() -> None:
    res = TurnResolution(
        time=NarrativeTime(bucket="breve", minutes=30),
        location="boar-inn",
        present=None,
    )
    delta = resolution_to_delta(res, previous_location="nfirea-lizzy-shop")
    assert delta.player_location == "boar-inn"
    assert delta.characters_active == []


def test_resolution_to_delta_keeps_null_present_without_move() -> None:
    res = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        location=None,
        present=None,
    )
    delta = resolution_to_delta(res, previous_location="boar-inn")
    assert delta.player_location is None
    assert delta.characters_active is None


def test_resolve_presence_for_location_change_helpers() -> None:
    from app.services.state_reducer import resolve_presence_for_location_change

    assert (
        resolve_presence_for_location_change(
            previous_location="shop",
            new_location="inn",
            present=None,
        )
        == []
    )
    assert resolve_presence_for_location_change(
        previous_location="shop",
        new_location="inn",
        present=["oste", "kael"],
    ) == ["oste", "kael"]
    assert (
        resolve_presence_for_location_change(
            previous_location="inn",
            new_location="inn",
            present=None,
        )
        is None
    )


def test_present_leave_same_location_registers_offscreen() -> None:
    from app.models.game_state import OffscreenCharacter

    state = GameState(
        session_id="s",
        player=PlayerState(location="nfirea-lizzy-shop"),
        characters_active=["nfirea", "lizzie-bareare"],
    )
    apply_scene_delta(
        state,
        SceneStateDelta(
            present_leave={
                "nfirea": OffscreenCharacter(
                    where="retrobottega",
                    reason="a cercare erbe",
                )
            }
        ),
    )
    assert state.characters_active == ["lizzie-bareare"]
    assert "nfirea" in state.characters_offscreen
    entry = state.characters_offscreen["nfirea"]
    assert entry.where == "retrobottega"
    assert entry.reason == "a cercare erbe"
    assert entry.from_location == "nfirea-lizzy-shop"
    assert state.characters["nfirea"].location == "retrobottega"


def test_present_leave_wins_over_present_and_join() -> None:
    from app.models.game_state import OffscreenCharacter

    state = GameState(
        session_id="s",
        player=PlayerState(location="boar-inn"),
        characters_active=["oste"],
    )
    apply_scene_delta(
        state,
        SceneStateDelta(
            characters_active=["oste", "kael"],
            present_join=["kael", "milo"],
            present_leave={
                "kael": OffscreenCharacter(where="gilda", reason="a iscriversi")
            },
        ),
    )
    assert "kael" not in state.characters_active
    assert "milo" in state.characters_active
    assert "oste" in state.characters_active
    assert state.characters_offscreen["kael"].where == "gilda"


def test_present_join_clears_offscreen_and_syncs_location() -> None:
    from app.models.game_state import OffscreenCharacter

    state = GameState(
        session_id="s",
        player=PlayerState(location="nfirea-lizzy-shop"),
        characters_active=["lizzie-bareare"],
        characters_offscreen={
            "nfirea": OffscreenCharacter(
                where="retrobottega",
                reason="erbe",
                from_location="nfirea-lizzy-shop",
            )
        },
    )
    apply_scene_delta(state, SceneStateDelta(present_join=["nfirea"]))
    assert "nfirea" in state.characters_active
    assert "nfirea" not in state.characters_offscreen
    assert state.characters["nfirea"].location == "nfirea-lizzy-shop"


def test_location_change_drops_offscreen_from_old_place() -> None:
    from app.models.game_state import OffscreenCharacter

    state = GameState(
        session_id="s",
        player=PlayerState(location="nfirea-lizzy-shop"),
        characters_active=[],
        characters_offscreen={
            "nfirea": OffscreenCharacter(
                where="retrobottega",
                reason="erbe",
                from_location="nfirea-lizzy-shop",
            ),
            "kael": OffscreenCharacter(
                where="gilda",
                reason="missione",
                from_location="boar-inn",
            ),
        },
    )
    apply_scene_delta(
        state,
        SceneStateDelta(player_location="boar-inn", characters_active=["oste"]),
    )
    assert "nfirea" not in state.characters_offscreen
    assert "kael" in state.characters_offscreen
    assert state.characters_active == ["oste"]


def test_coerce_present_leave_shapes() -> None:
    from app.models.game_state import coerce_present_leave

    as_list = coerce_present_leave(
        [{"id": "milo", "where": "retrobottega", "reason": "erbe"}]
    )
    assert as_list["milo"].where == "retrobottega"
    assert as_list["milo"].reason == "erbe"

    as_dict = coerce_present_leave(
        {"kael": {"where": "gilda", "reason": "iscrizione"}}
    )
    assert as_dict["kael"].where == "gilda"

    as_ids = coerce_present_leave(["nfirea", "oste"])
    assert set(as_ids) == {"nfirea", "oste"}

    res = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        present_leave=[{"id": "milo", "where": "cortile", "reason": "a parlare"}],
        present_join=["kael"],
    )
    delta = resolution_to_delta(res)
    assert delta.present_leave["milo"].where == "cortile"
    assert delta.present_join == ["kael"]


def test_present_review_dropped_npc_goes_offscreen() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(location="boar-inn"),
        characters_active=["oste", "kael"],
    )
    result = PresentReviewResult(characters_active=["oste"])
    delta = present_review_to_delta(result, apply_presence=True, state=state)
    assert delta.characters_active == ["oste"]
    assert "kael" in delta.present_leave
    apply_scene_delta(state, delta)
    assert state.characters_active == ["oste"]
    assert "kael" in state.characters_offscreen
    assert state.characters_offscreen["kael"].from_location == "boar-inn"


def test_format_offscreen_lines() -> None:
    from app.models.game_state import OffscreenCharacter
    from app.services.state_reducer import format_offscreen_lines

    state = GameState(
        session_id="s",
        characters_offscreen={
            "nfirea": OffscreenCharacter(where="retrobottega", reason="erbe"),
            "solo": OffscreenCharacter(),
        },
    )
    lines = format_offscreen_lines(state)
    assert "nfirea — retrobottega: erbe" in lines
    assert "solo" in lines
