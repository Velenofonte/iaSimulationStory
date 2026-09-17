"""Undo checkpoint stack (fino a 3) senza LLM."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import deps as api_deps
from app.api import routes as routes_mod
from app.config import settings
from app.main import app
from app.models import ChatMessage
from app.models.game_state import NpcKnowledgeFact
from app.services.save_manager import SaveManager
from tests.conftest import make_seed_story


def test_undo_checkpoint_roundtrip_restores_state_chat_wiki(tmp_path: Path) -> None:
    saves = SaveManager(tmp_path)
    state = saves.create_session("Rion", "e-rantel")
    sid = state.session_id

    wiki_file = saves.wiki_dir(sid) / "locations" / "e-rantel.md"
    wiki_file.parent.mkdir(parents=True, exist_ok=True)
    original_wiki = "# E-Rantel\noriginal\n"
    wiki_file.write_text(original_wiki, encoding="utf-8")

    chat_before = saves.chat_path(sid).read_text(encoding="utf-8")
    gs_before = saves.game_state_path(sid).read_text(encoding="utf-8")

    assert not saves.has_undo_checkpoint(sid)
    saves.write_undo_checkpoint(sid)
    assert saves.has_undo_checkpoint(sid)
    assert saves.undo_count(sid) == 1

    state.player.location = "carne"
    state.situations.append(NpcKnowledgeFact(id="poisoned_lore", summary="poisoned lore"))
    saves.save_game_state(state)
    saves.append_chat(sid, ChatMessage(role="user", content="ranghi?", location="carne"))
    saves.append_chat(
        sid, ChatMessage(role="assistant", content="Porpora Verde", location="carne")
    )
    wiki_file.write_text("# E-Rantel\nmutated\n", encoding="utf-8")

    restored = saves.restore_undo_checkpoint(sid)
    assert restored.player.location == "e-rantel"
    assert "poisoned lore" not in restored.situations
    assert saves.chat_path(sid).read_text(encoding="utf-8") == chat_before
    assert saves.game_state_path(sid).read_text(encoding="utf-8") == gs_before
    assert wiki_file.read_text(encoding="utf-8") == original_wiki
    assert not saves.has_undo_checkpoint(sid)


def test_undo_stack_keeps_last_three(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "undo_checkpoint_depth", 3)
    saves = SaveManager(tmp_path)
    state = saves.create_session("Rion", "e-rantel")
    sid = state.session_id

    locations: list[str] = []
    for loc in ("a", "b", "c", "d"):
        saves.write_undo_checkpoint(sid)
        locations.append(state.player.location)
        state.player.location = loc
        saves.save_game_state(state)

    assert saves.undo_count(sid) == 3

    # Stack holds pre-b, pre-c, pre-d (oldest dropped was pre-a / start)
    r1 = saves.restore_undo_checkpoint(sid)
    assert r1.player.location == "c"
    assert saves.undo_count(sid) == 2

    r2 = saves.restore_undo_checkpoint(sid)
    assert r2.player.location == "b"
    assert saves.undo_count(sid) == 1

    r3 = saves.restore_undo_checkpoint(sid)
    assert r3.player.location == "a"
    assert saves.undo_count(sid) == 0


def test_undo_api_stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_llm) -> None:
    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "undo_checkpoint_depth", 3)
    make_seed_story(tmp_path)
    saves = SaveManager(root=tmp_path / "saves")
    monkeypatch.setattr(api_deps, "saves", saves)
    monkeypatch.setattr(routes_mod, "saves", saves)
    client = TestClient(app)

    created = client.post(
        "/api/session",
        json={
            "story_id": "overlord",
            "origin": "custom",
            "player_name": "Rion",
            "race": "human",
            "start_mode": "free",
        },
    )
    assert created.status_code == 200
    sid = created.json()["session_id"]
    assert client.get(f"/api/session/{sid}/can-undo").json() == {
        "can_undo": False,
        "undo_count": 0,
    }

    for i in range(3):
        chat = client.post(
            "/api/chat", json={"session_id": sid, "message": f"Azione {i}."}
        )
        assert chat.status_code == 200
        assert chat.json()["undo_count"] == i + 1

    assert client.get(f"/api/session/{sid}/can-undo").json()["undo_count"] == 3

    # Quarto turno: depth resta 3
    chat4 = client.post("/api/chat", json={"session_id": sid, "message": "Azione 3."})
    assert chat4.status_code == 200
    assert chat4.json()["undo_count"] == 3

    messages = client.get(f"/api/chat/{sid}").json()
    undo = client.post(f"/api/session/{sid}/undo-last-turn")
    assert undo.status_code == 200
    assert undo.json()["undo_count"] == 2
    assert len(undo.json()["messages"]) == len(messages) - 2

    undo2 = client.post(f"/api/session/{sid}/undo-last-turn")
    assert undo2.status_code == 200
    assert undo2.json()["undo_count"] == 1

    undo3 = client.post(f"/api/session/{sid}/undo-last-turn")
    assert undo3.status_code == 200
    assert undo3.json()["undo_count"] == 0
    assert undo3.json()["can_undo"] is False

    again = client.post(f"/api/session/{sid}/undo-last-turn")
    assert again.status_code == 409
