"""API smoke tests with mocked LLM."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.api import deps as api_deps
from app.api import routes as routes_mod
from app.services.save_manager import SaveManager
from tests.conftest import make_seed_story


def test_session_and_chat_shape(tmp_path: Path, monkeypatch, fake_llm) -> None:
    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    make_seed_story(tmp_path)
    saves = SaveManager(root=tmp_path / "saves")
    monkeypatch.setattr(api_deps, "saves", saves)
    monkeypatch.setattr(routes_mod, "saves", saves)

    fake_llm["responses"] = [
        json.dumps(
            {
                "time": {"bucket": "istantanea", "minutes": 3},
                "location": None,
                "present": None,
                "spells": [],
                "scene_brief": ["Sei a E-Rantel."],
            }
        ),
        json.dumps({"text": "La citta' brulica di vita."}),
    ]

    client = TestClient(app)
    r = client.post(
        "/api/session",
        json={"player_name": "Tester", "story_id": "overlord"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert "state" in body
    assert "messages" in body
    sid = body["session_id"]

    r2 = client.post("/api/chat", json={"session_id": sid, "message": "guardo intorno"})
    assert r2.status_code == 200
    chat = r2.json()
    assert "reply" in chat and chat["reply"]
    assert "state" in chat
    assert "present_review_ran" in chat
    assert "consolidation_ran" in chat
    assert "input_tokens" in chat
    assert isinstance(chat["input_tokens"], int)
