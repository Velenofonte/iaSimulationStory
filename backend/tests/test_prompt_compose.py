"""Smoke tests for composed system prompts (no giant snapshots)."""

from app.services.consequence_engine import ConsequenceEngine
from app.services.llm_client import LLMClient
from app.models import GameState, PlayerState


def test_compose_turn_resolve_includes_shared() -> None:
    text = LLMClient().compose_prompt("turn_resolve")
    assert "TurnResolution" in text
    assert "Grammatica player_action" in text
    assert "Lente NPC" in text
    assert "Registro ID" in text
    for key in (
        "time",
        "location",
        "present",
        "present_join",
        "present_leave",
        "spells",
        "scene_brief",
        "situations_add",
        "situations_remove",
        "npc_knowledge_upsert",
        "deed",
    ):
        assert f'"{key}"' in text


def test_compose_narrative_render_includes_grammar_and_epistemic() -> None:
    text = LLMClient().compose_prompt("narrative_render")
    assert "NarrativeRenderResult" in text
    assert '"text"' in text
    assert "Grammatica player_action" in text
    assert "Lente NPC" in text
    assert "Registro ID" not in text


def test_compose_review_present_includes_id_registry() -> None:
    text = LLMClient().compose_prompt("review_present")
    assert "PresentReviewResult" in text
    assert "Registro ID" in text
    assert "front_id" in text
    assert "max **6**" in text or "max **6** situations" in text
    for key in (
        "player_location",
        "characters_active",
        "situations_add",
        "situations_remove",
        "npc_knowledge_upsert",
        "present_leave",
        "confidence",
    ):
        assert f'"{key}"' in text


def test_compose_review_consolidate_nested_character_updates() -> None:
    text = LLMClient().compose_prompt("review_consolidate")
    assert "ConsolidationReviewResult" in text
    assert "character_updates" in text
    assert "state_cleanup" in text
    assert '"prova"' in text  # nested player id example


def test_engine_ingest_has_no_yggdrasil_lore() -> None:
    text = LLMClient().compose_prompt("ingest")
    assert "YGGDRASIL" not in text
    assert "saves/" in text


def test_present_user_prompt_is_data_only() -> None:
    eng = ConsequenceEngine.__new__(ConsequenceEngine)
    eng.saves = None  # type: ignore[assignment]
    eng._valid_location_ids = lambda: ["e-rantel"]  # type: ignore[method-assign]
    eng._format_game_state = lambda state: "STATE"  # type: ignore[method-assign]
    state = GameState(session_id="t", player=PlayerState(name="Prova", location="e-rantel"))
    user = eng._build_present_user(state, "user: ciao")
    assert "Applica il system prompt" in user
    assert "5 e 12" not in user
    assert "stringhe ESATTE" not in user
    assert "Mantieni le situations attive tra 1 e 6" not in user


def test_pending_thread_hint_uses_id_summary() -> None:
    from app.services.turn_resolver import _PENDING_THREAD_HINT

    assert '"id"' in _PENDING_THREAD_HINT or "id" in _PENDING_THREAD_HINT
    assert "summary" in _PENDING_THREAD_HINT
    assert "stringa breve" not in _PENDING_THREAD_HINT


def test_compose_cast_and_travel_rules() -> None:
    resolve = LLMClient().compose_prompt("turn_resolve")
    render = LLMClient().compose_prompt("narrative_render")
    present = LLMClient().compose_prompt("review_present")
    assert "acting_cast" in render
    assert "chat_recent` batte `present` stale" not in resolve
    assert "chat_recent` batte present stale" not in render
    assert "spostamento" in resolve
    assert "gilda-avventurieri" in present
