"""Character creation: lore / custom + arc / free."""

from __future__ import annotations

from pathlib import Path

import frontmatter
from fastapi.testclient import TestClient

from app.api import routes as routes_mod
from app.config import settings
from app.main import app
from app.services.save_manager import SaveManager
from app.services.story_catalog import list_fronts, list_playable_characters, list_races
from tests.conftest import make_seed_story


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    make_seed_story(tmp_path)
    # Enable default front for arc tests that want it
    meta = tmp_path / "stories" / "overlord" / "meta.yaml"
    text = meta.read_text(encoding="utf-8").replace("default_front:\n", "default_front: carne_arc\n")
    meta.write_text(text, encoding="utf-8")
    saves = SaveManager(root=tmp_path / "saves")
    monkeypatch.setattr(routes_mod, "saves", saves)
    return TestClient(app)


def test_catalog_endpoints(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert [p["id"] for p in list_playable_characters("overlord")] == ["enri"]
    assert {r["id"] for r in list_races("overlord")} == {"human", "elf"}
    assert any(f["id"] == "carne_arc" for f in list_fronts("overlord"))

    r = client.get("/api/stories/overlord/playable")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "Enri Emmot"
    assert client.get("/api/stories/overlord/races").status_code == 200
    assert client.get("/api/stories/overlord/fronts").json()[0]["id"] == "carne_arc"

    sheet = client.get("/api/stories/overlord/playable/enri")
    assert sheet.status_code == 200
    body = sheet.json()
    assert body["id"] == "enri"
    assert "Coraggiosa" in body["body"]
    assert body.get("spells") == []
    assert client.get("/api/stories/overlord/playable/ainz").status_code == 404


def test_lore_ainz_gets_seed_spellbook(tmp_path: Path, monkeypatch, fake_llm) -> None:
    """Clone real overlord seed so ainz spellbook is present."""
    monkeypatch.setattr(settings, "project_root", Path(__file__).resolve().parents[2])
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    saves = SaveManager(root=tmp_path / "saves")
    monkeypatch.setattr(routes_mod, "saves", saves)
    client = TestClient(app)

    preview = client.get("/api/stories/overlord/playable/ainz")
    assert preview.status_code == 200
    assert any(s["name"] == "Grasp Heart" for s in preview.json()["spells"])

    r = client.post(
        "/api/session",
        json={
            "story_id": "overlord",
            "origin": "lore",
            "character_id": "ainz",
            "start_mode": "free",
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    book = client.get(f"/api/session/{sid}/spellbook").json()
    assert book["player_id"] == "ainz"
    names = {s["name"] for s in book["spells"]}
    assert "Grasp Heart" in names
    assert "Create Middle Tier Undead" in names


def test_create_lore_binds_sheet_no_rewrite(tmp_path: Path, monkeypatch, fake_llm) -> None:
    client = _client(tmp_path, monkeypatch)
    before = (tmp_path / "stories" / "overlord" / "wiki" / "characters" / "enri.md").read_text(
        encoding="utf-8"
    )
    r = client.post(
        "/api/session",
        json={
            "story_id": "overlord",
            "origin": "lore",
            "character_id": "enri",
            "start_mode": "free",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    state = body["state"]
    assert state["player"]["name"] == "Enri Emmot"
    assert state["player"]["character_id"] == "enri"
    assert state["player"]["origin"] == "lore"
    assert state["fronts"] == {}
    assert fake_llm["calls"] == []

    sid = body["session_id"]
    sheet_path = tmp_path / "saves" / sid / "wiki" / "characters" / "enri.md"
    post = frontmatter.load(sheet_path)
    assert post.metadata.get("role") == "player"
    assert "Coraggiosa" in post.content
    # Seed unchanged
    assert (tmp_path / "stories" / "overlord" / "wiki" / "characters" / "enri.md").read_text(
        encoding="utf-8"
    ) == before

    sheet = client.get(f"/api/session/{sid}/sheet").json()
    assert sheet["id"] == "enri"
    assert sheet["role"] == "player"
    book = client.get(f"/api/session/{sid}/spellbook").json()
    assert book["player_id"] == "enri"


def test_create_custom_llm_sheet(tmp_path: Path, monkeypatch, fake_llm) -> None:
    client = _client(tmp_path, monkeypatch)
    fake_llm["responses"] = [
        "---\nid: momonga\nname: Momonga\ntype: character\ntier: minimal\n"
        "role: player\nrace: undead\nlocation: e-rantel\n---\n\n"
        "# Personalita\nCauto e pragmatico.\n\n"
        "# Aspetto fisico\nScheletro con orbi rossi.\n\n"
        "# Obiettivi\nProteggere la gilda.\n\n"
        "# Capacita di combattimento\nOverlord lv 100.\n\n"
        "# Knowledge scope\nsa: YGGDRASIL\nnon sa: Nuovo Mondo\n\n"
        "# Relazione col giocatore\n0\n\n"
        "# Memorie\n\n"
        "# Open threads\n"
    ]
    r = client.post(
        "/api/session",
        json={
            "story_id": "overlord",
            "origin": "custom",
            "player_name": "Momonga",
            "race": "human",
            "details": "player lv 100 necromancer",
            "start_mode": "free",
        },
    )
    assert r.status_code == 200, r.text
    state = r.json()["state"]
    assert state["player"]["character_id"] == "momonga"
    assert state["player"]["race"] == "human"
    assert state["player"]["origin"] == "custom"
    assert state["fronts"] == {}
    assert fake_llm["calls"], "LLM should have been called"

    sid = r.json()["session_id"]
    sheet = client.get(f"/api/session/{sid}/sheet").json()
    assert sheet["id"] == "momonga"
    assert "Cauto e pragmatico" in sheet["body"]
    assert sheet["role"] == "player"


def test_start_mode_arc_activates_front(tmp_path: Path, monkeypatch, fake_llm) -> None:
    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/api/session",
        json={
            "story_id": "overlord",
            "origin": "custom",
            "player_name": "Hero",
            "start_mode": "arc",
            "front_id": "carne_arc",
        },
    )
    assert r.status_code == 200, r.text
    fronts = r.json()["state"]["fronts"]
    assert "carne_arc" in fronts
    assert fronts["carne_arc"]["status"] == "active"


def test_start_mode_free_no_front(tmp_path: Path, monkeypatch, fake_llm) -> None:
    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/api/session",
        json={
            "story_id": "overlord",
            "origin": "custom",
            "player_name": "Hero",
            "start_mode": "free",
        },
    )
    assert r.status_code == 200
    assert r.json()["state"]["fronts"] == {}


def test_start_mode_free_after_arc_resolves(tmp_path: Path, monkeypatch, fake_llm) -> None:
    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/api/session",
        json={
            "story_id": "overlord",
            "origin": "custom",
            "player_name": "Hero",
            "start_mode": "free",
            "front_id": "carne_arc",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    state = body["state"]
    fronts = state["fronts"]
    assert fronts["carne_arc"]["status"] == "resolved"
    assert state["player"]["location"] == "e-rantel"
    assert "ainz" not in (state.get("characters_active") or [])

    session_id = body["session_id"]
    erantel = (
        tmp_path / "saves" / session_id / "wiki" / "locations" / "e-rantel.md"
    ).read_text(encoding="utf-8")
    assert "Arco di Carne chiuso" in erantel or "post-arco" in erantel


def test_lore_rejects_unknown_character(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/api/session",
        json={
            "story_id": "overlord",
            "origin": "lore",
            "character_id": "ainz",
            "start_mode": "free",
        },
    )
    assert r.status_code == 400
