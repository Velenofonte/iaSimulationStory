"""Basic tests for game state and save manager."""

from pathlib import Path

from app.models import GameState, PlayerState, PresentReviewResult
from app.models.game_state import NpcKnowledgeFact
from app.services.consequence_engine import ConsequenceEngine
from app.services.save_manager import SaveManager


def test_session_roundtrip(tmp_path: Path) -> None:
    saves = SaveManager(tmp_path)
    state = saves.create_session("Rion", "e-rantel")
    state.situations.append(NpcKnowledgeFact(id="test_situation", summary="test situation"))
    saves.save_game_state(state)
    loaded = saves.load_game_state(state.session_id)
    assert loaded.player.name == "Rion"
    assert any(s.summary == "test situation" for s in loaded.situations)


def test_delete_session_removes_dir_and_clears_active(tmp_path: Path) -> None:
    saves = SaveManager(tmp_path)
    state = saves.create_session("Rion", "e-rantel")
    sid = state.session_id
    session_path = tmp_path / sid
    wiki = session_path / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "characters").mkdir(exist_ok=True)
    (wiki / "characters" / "rion.md").write_text("# Rion\n", encoding="utf-8")
    assert saves.get_active_session_id() == sid
    assert (session_path / "game_state.json").exists()
    assert (wiki / "characters" / "rion.md").exists()

    saves.delete_session(sid)
    assert not session_path.exists()
    assert not (session_path / "game_state.json").exists()
    assert not wiki.exists()
    assert saves.get_active_session_id() is None
    assert saves.list_sessions() == []


def test_present_review_merge() -> None:
    engine = ConsequenceEngine()
    state = GameState(session_id="test", player=PlayerState(location="e-rantel"))
    before_time = state.time
    result = PresentReviewResult(
        player_location="e-rantel/tavern",
        time="Giorno 99 · notte",
        characters_active=["npc1"],
        situations_add=["birra sul tavolo"],
    )
    engine.apply_present_review(state, result)
    assert state.player.location == "e-rantel/tavern"
    assert state.characters_active == ["npc1"]
    assert any(s.summary == "birra sul tavolo" for s in state.situations)
    assert state.time == before_time  # orologio non toccato dalla review


def test_present_review_accepts_null_lists() -> None:
    result = PresentReviewResult.model_validate(
        {
            "characters_active": ["enri"],
            "front_impacts": None,
            "situations_add": None,
            "situations_remove": None,
            "extra_set": None,
        }
    )
    assert result.front_impacts == []
    assert result.situations_add == []
    assert result.extra_set == {}


def test_present_review_coerces_objects_dict() -> None:
    result = PresentReviewResult.model_validate(
        {
            "characters_active": ["impiegata"],
            "location_updates": {
                "e-rantel": {
                    "atmosphere": "chiasso di gilda",
                    "objects": {
                        "bancone": "lungo e occupato",
                        "bacheca": "richieste di incarico",
                    },
                },
                "gilda": {
                    "objects": {
                        "gilda_avventurieri": {"bancone": "legno scuro", "odore": "birra"},
                    },
                },
            },
        }
    )
    objs = result.location_updates["e-rantel"].objects
    assert any("bancone" in o for o in objs)
    assert any("bacheca" in o for o in objs)
    nested = result.location_updates["gilda"].objects
    assert len(nested) == 1
    assert "gilda_avventurieri" in nested[0]
    assert "bancone" in nested[0]


def test_present_review_always_replaces_characters() -> None:
    engine = ConsequenceEngine()
    state = GameState(
        session_id="test",
        player=PlayerState(location="carne"),
        characters_active=["vecchio-npc", "ghost"],
    )
    # LLM omits / null → lista vuota, NON lasciare stale
    result = PresentReviewResult.model_validate(
        {"player_location": "carne", "characters_active": None}
    )
    engine.apply_present_review(state, result)
    assert state.characters_active == []

    result2 = PresentReviewResult(
        player_location="carne",
        characters_active=["donna del villaggio", {"name": "locandiere"}],
    )
    engine.apply_present_review(state, result2)
    assert state.characters_active == ["donna del villaggio", "locandiere"]


def test_missing_session_does_not_create_dir(tmp_path: Path) -> None:
    saves = SaveManager(tmp_path)
    missing = "no-such-session"
    try:
        saves.load_game_state(missing)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")
    assert not (tmp_path / missing).exists()


def test_stale_active_does_not_create_dir(tmp_path: Path) -> None:
    saves = SaveManager(tmp_path)
    saves.active_path().write_text('{"session_id": "ghost"}', encoding="utf-8")
    assert saves.get_active_session_id() is None
    assert not (tmp_path / "ghost").exists()


def test_create_session_writes_welcome(tmp_path: Path) -> None:
    saves = SaveManager(tmp_path)
    state = saves.create_session("Rion", start_location="e-rantel")
    chat = saves.load_all_chat(state.session_id)
    assert len(chat) == 1
    assert chat[0].role == "assistant"
    assert "E-Rantel" in chat[0].content
    assert "Overlord" in chat[0].content


def test_present_review_normalizes_carne_alias() -> None:
    engine = ConsequenceEngine()
    state = GameState(session_id="test", player=PlayerState(location="e-rantel"))
    engine.apply_present_review(
        state,
        PresentReviewResult(
            player_location="Villaggio di Carne",
            characters_active=[],
        ),
    )
    assert state.player.location == "carne"

