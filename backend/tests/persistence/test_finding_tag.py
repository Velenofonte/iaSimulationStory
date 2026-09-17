"""Chat persistence: finding tag on assistant when turn has private findings."""

from __future__ import annotations

from pathlib import Path

from app.models.game_state import GameState, PlayerState
from app.persistence.save_manager import SaveManager
from app.persistence.turn_persistence import commit_turn
from app.wiki.wiki_writer import WikiWriter


def test_commit_turn_marks_assistant_finding(tmp_path: Path) -> None:
    saves = SaveManager(root=tmp_path / "saves")
    sid = "sess-findings"
    wiki_dir = tmp_path / "saves" / sid / "wiki"
    wiki = WikiWriter(wiki_dir=wiki_dir)
    state = GameState(
        session_id=sid,
        story_id="overlord",
        player=PlayerState(name="Rayan", character_id="rayan", location="e-rantel"),
    )
    saves.save_game_state(state)
    wiki.ensure_player("Rayan", "e-rantel", character_id="rayan")

    commit_turn(
        saves,
        wiki,
        state,
        user_message="[Detect Power]",
        reply="Percepisci un'aura.",
        present=[],
        tags=["overt"],
        has_findings=True,
    )
    chat = saves.load_all_chat(sid)
    assert chat[-2].role == "user"
    assert "finding" not in chat[-2].tags
    assert chat[-1].role == "assistant"
    assert "finding" in chat[-1].tags
