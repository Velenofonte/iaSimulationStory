"""Smoke tests for composed system prompts (no giant snapshots)."""

from app.services.consequence_engine import ConsequenceEngine
from app.services.llm_client import LLMClient
from app.models import GameState, PlayerState


def test_compose_turn_resolve_includes_shared() -> None:
    text = LLMClient().compose_prompt("turn_resolve")
    assert "TurnResolution" in text
    assert "Grammatica player_action" in text
    assert "Lente NPC" in text
    assert "Lente PG" in text
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
        "player_findings_add",
        "player_findings_reveal",
        "npc_knowledge_upsert",
        "deed",
    ):
        assert f'"{key}"' in text


def test_compose_turn_resolve_mentions_spell_tags_and_findings() -> None:
    text = LLMClient().compose_prompt("turn_resolve")
    assert "player_findings_add" in text
    assert "output: info" in text or "output:info" in text or "`output: info`" in text
    assert "Lente PG" in text
    npc = LLMClient().compose_prompt("narrative_render")
    assert "player_findings" in npc
    assert "manifest: visible" in npc or "manifest" in npc


def test_compose_narrative_render_includes_grammar_and_epistemic() -> None:
    text = LLMClient().compose_prompt("narrative_render")
    assert "NarrativeRenderResult" in text
    assert '"text"' in text
    assert "Grammatica player_action" in text
    assert "Lente NPC" in text
    assert "Lente PG" in text
    assert "Registro ID" not in text


def test_compose_review_present_includes_id_registry() -> None:
    text = LLMClient().compose_prompt("review_present")
    assert "PresentReviewResult" in text
    assert "beat_commit" in text
    assert "still_live" in text
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


def test_compose_turn_resolve_mentions_story_so_far() -> None:
    text = LLMClient().compose_prompt("turn_resolve")
    assert "story_so_far" in text


def test_compose_narrative_render_mentions_story_so_far() -> None:
    text = LLMClient().compose_prompt("narrative_render")
    assert "story_so_far" in text


def test_compose_era_digest_prompt_exists() -> None:
    text = LLMClient().compose_prompt("era_digest")
    assert "reach" in text
    assert "chronicle" in text


def test_compose_review_arc_close_exists() -> None:
    text = LLMClient().compose_prompt("review_arc_close")
    assert "chronicle" in text
    assert "reach" in text



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


def test_compose_prompts_forbid_narrator_self_conclusive_actions() -> None:
    resolve = LLMClient().compose_prompt("turn_resolve")
    render = LLMClient().compose_prompt("narrative_render")
    for text in (resolve, render):
        assert "auto-conclusione" in text
        assert "impatto" in text
        assert "in corso" in text
        assert "meteorite" not in text


def test_compose_front_due_now_and_on_site_summaries() -> None:
    resolve = LLMClient().compose_prompt("turn_resolve")
    render = LLMClient().compose_prompt("narrative_render")
    assert "front_live" in resolve or "front_due_now" in resolve
    assert "beat_commit" in resolve
    assert "means_inflight" in resolve
    assert "pillar_failed" in resolve
    assert "hold_reason" in resolve
    assert "hold_reason" in render
    assert "still_live" in resolve
    assert "canon_facts.location" in resolve
    assert "settore" in resolve or "tratto" in resolve
    assert "fired_beat_summaries" in render
    assert "front_live" in render
    assert "settore" in render or "tratto" in render or "lontano" in render
    assert "means_inflight" in render or "in volo" in render
    assert "spam" in resolve or "un mezzo" in resolve
    assert "atterra" in resolve or "atterrare" in resolve
    assert "VIETATO `still_live` su wait" in resolve or "still_live` su wait" in resolve
    assert "micro" in render or "atterra" in render