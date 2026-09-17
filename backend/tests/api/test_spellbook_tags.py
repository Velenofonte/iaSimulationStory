"""API: spellbook tags endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import deps as api_deps
from app.api import routes as routes_mod
from app.application.session_context import build_session_services
from app.config import settings
from app.main import app
from app.services.save_manager import SaveManager
from tests.conftest import make_seed_story


def test_spellbook_tags_get_and_post(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    make_seed_story(tmp_path)
    saves = SaveManager(root=tmp_path / "saves")
    monkeypatch.setattr(api_deps, "saves", saves)
    monkeypatch.setattr(routes_mod, "saves", saves)

    client = TestClient(app)
    r = client.post(
        "/api/session",
        json={"player_name": "Rayan", "story_id": "overlord"},
    )
    assert r.status_code == 200
    sid = r.json()["session_id"]

    svc = build_session_services(sid, saves=saves)
    svc.wiki.track_spells(
        "Rayan",
        {"Detect Power": "rileva e identifica forme di vita"},
        character_id="rayan",
    )

    g = client.get(f"/api/session/{sid}/spellbook")
    assert g.status_code == 200
    body = g.json()
    assert body["spells"]
    detect = next(s for s in body["spells"] if s["name"] == "Detect Power")
    assert detect["output"] == "info"
    assert detect["manifest"] == "visible"

    p = client.post(
        f"/api/session/{sid}/spellbook/tags",
        json={
            "updates": [
                {"name": "Detect Power", "output": "info", "manifest": "subtle"}
            ]
        },
    )
    assert p.status_code == 200
    updated = next(s for s in p.json()["spells"] if s["name"] == "Detect Power")
    assert updated["manifest"] == "subtle"
