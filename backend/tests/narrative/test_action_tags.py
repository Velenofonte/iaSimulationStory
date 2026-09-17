"""Action tags + chat meta (present/location/tags) for epistemic firewall."""

from __future__ import annotations

from pathlib import Path

from app.models import ChatMessage
from app.narrative.action_tags import ensure_tags, tag_player_action
from app.narrative.narrative_context import NarrativeContextAssembler
from app.persistence.save_manager import SaveManager
from app.persistence.turn_persistence import commit_turn
from app.services.llm_client import LLMClient
from app.wiki.wiki_writer import WikiWriter
from tests.conftest import make_seed_story


def test_tag_dialogue_overt() -> None:
    tags = tag_player_action('"Mi scusi, va tutto bene?" dico alla guardia')
    assert "dialogue" in tags
    assert "overt" in tags
    assert "stealth" not in tags


def test_tag_stealth_fly_no_overt() -> None:
    msg = (
        "Fuori da occhi indiscreti casto [fly - magia di 3 tier] "
        "e decido di guardare la situazione dal alto"
    )
    tags = tag_player_action(msg)
    assert "stealth" in tags
    assert "overt" not in tags


def test_tag_stealth_and_hide_mutually_exclude_overt() -> None:
    tags = tag_player_action("mi nascondo dietro il muro di nascosto")
    assert "hide" in tags or "stealth" in tags
    assert "overt" not in tags


def test_tag_wait() -> None:
    tags = tag_player_action(
        "aspetto finche non succede qualcosa d'interessante",
        stance="wait",
    )
    assert tags == ["wait"] or "wait" in tags
    assert "overt" not in tags


def test_tag_private_and_dialogue() -> None:
    tags = tag_player_action('*sembra la quiete prima della tempesta* "Forse meglio scendere" dico')
    assert "private" in tags
    assert "dialogue" in tags


def test_ensure_tags_legacy_retags() -> None:
    tags = ensure_tags(
        "Fuori da occhi indiscreti uso [invisibility]",
        [],
    )
    assert "stealth" in tags
    assert "overt" not in tags


def test_ensure_tags_keeps_stored_and_strips_overt_with_stealth() -> None:
    tags = ensure_tags("whatever", ["stealth", "overt", "dialogue"])
    assert "stealth" in tags
    assert "dialogue" in tags
    assert "overt" not in tags


def test_commit_turn_persists_present_and_tags(tmp_path: Path, monkeypatch) -> None:
    make_seed_story(tmp_path)
    from app.config import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    saves = SaveManager(root=tmp_path / "saves")
    state = saves.create_session("Hero", start_location="e-rantel", story_id="overlord")
    state.characters_active = ["enri"]
    wiki = WikiWriter(wiki_dir=saves.wiki_dir(state.session_id))

    commit_turn(
        saves,
        wiki,
        state,
        user_message='Fuori da occhi indiscreti casto [fly] e guardo dall\'alto',
        reply="Sali in silenzio. Nessuno ti nota.",
        present=["enri"],
        tags=["stealth"],
        stance="action",
    )

    chat = saves.load_all_chat(state.session_id)
    # welcome + user + assistant
    user = next(m for m in chat if m.role == "user")
    assistant = [m for m in chat if m.role == "assistant"][-1]
    assert user.present == ["enri"]
    assert user.tags == ["stealth"]
    assert user.location == "e-rantel"
    assert assistant.present == ["enri"]
    assert assistant.tags == ["stealth"]


def test_compress_chat_propagates_meta(tmp_path: Path, monkeypatch) -> None:
    make_seed_story(tmp_path)
    from app.config import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    # Minimal assembler deps: only need _compress_chat
    class _A(NarrativeContextAssembler):
        def __init__(self) -> None:
            pass

    asm = _A.__new__(_A)
    recent = [
        ChatMessage(
            role="user",
            content="Fuori da occhi casto [fly]",
            location="great-wall",
            present=[],
            tags=[],  # legacy → retag
        ),
        ChatMessage(
            role="assistant",
            content="Sali nascosto.",
            location="great-wall",
            present=[],
            tags=[],
        ),
    ]
    turns = NarrativeContextAssembler._compress_chat(asm, recent)
    assert len(turns) == 2
    assert turns[0].location == "great-wall"
    assert "stealth" in turns[0].tags
    assert "overt" not in turns[0].tags
    assert turns[1].tags == turns[0].tags


def test_compose_prompts_mention_chat_meta() -> None:
    text = LLMClient().compose_prompt("narrative_render")
    assert "stealth" in text
    assert "chat_recent" in text
    assert "Lente NPC" in text
    resolve = LLMClient().compose_prompt("turn_resolve")
    assert "stealth" in resolve
    assert "dall'alto" in resolve or "dall'alto" in text
