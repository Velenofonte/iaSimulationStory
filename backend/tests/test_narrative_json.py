"""Tests for structured narrative request/reply and clock advance."""

from pathlib import Path

from app.models import GameState, PlayerState
from app.models.narrative import NarrativeReply, NarrativeRequest
from app.services.game_clock import advance_from_parts, normalize_bucket
from app.services.narrative_engine import NarrativeEngine


def test_normalize_bucket_aliases() -> None:
    assert normalize_bucket("short") == "breve"
    assert normalize_bucket("instant") == "istantanea"
    assert normalize_bucket("rest") == "riposo"


def test_estimate_tokens() -> None:
    from app.services.token_estimate import estimate_tokens

    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 40) == 10


def test_advance_from_parts() -> None:
    state = GameState(session_id="t", day=1, minutes=480)
    kind, delta = advance_from_parts(state, "istantanea", 5)
    assert kind == "istantanea"
    assert delta == 5
    assert state.minutes == 485
    assert "08:05" in state.time


def test_narrative_reply_schema() -> None:
    reply = NarrativeReply.model_validate(
        {
            "text": "Guardi il bosco.",
            "time": {"bucket": "short", "minutes": 40},
            "spells": [],
        }
    )
    assert reply.text == "Guardi il bosco."
    assert reply.time.bucket == "short"
    assert normalize_bucket(reply.time.bucket) == "breve"


def test_narrative_reply_coerces_spell_strings() -> None:
    reply = NarrativeReply.model_validate(
        {
            "text": "La luce si accende.",
            "time": {"bucket": "istantanea", "minutes": 3},
            "spells": [
                "Luce — magia di tier 1 permette di far risplendere un oggetto",
                {"name": "Fly", "description": "volare"},
            ],
        }
    )
    assert len(reply.spells) == 2
    assert reply.spells[0].name == "Luce"
    assert "tier 1" in reply.spells[0].description
    assert reply.spells[1].name == "Fly"


def test_narrative_reply_optional_location() -> None:
    reply = NarrativeReply.model_validate(
        {
            "text": "Arrivi a Carne.",
            "time": {"bucket": "media", "minutes": 120},
            "location": "carne",
            "spells": [],
        }
    )
    assert reply.location == "carne"
    bare = NarrativeReply.model_validate(
        {"text": "Resti fermo.", "time": {"bucket": "istantanea", "minutes": 2}}
    )
    assert bare.location is None


def test_narrative_reply_present_list() -> None:
    reply = NarrativeReply.model_validate(
        {
            "text": "Parli con la donna.",
            "time": {"bucket": "istantanea", "minutes": 3},
            "present": ["donna del villaggio", {"name": "uomo sulla panca"}],
        }
    )
    assert reply.present == ["donna del villaggio", "uomo sulla panca"]
    alone = NarrativeReply.model_validate(
        {
            "text": "Sei solo.",
            "time": {"bucket": "istantanea", "minutes": 2},
            "present": [],
        }
    )
    assert alone.present == []
    unchanged = NarrativeReply.model_validate(
        {"text": "Ok.", "time": {"bucket": "istantanea", "minutes": 1}}
    )
    assert unchanged.present is None


def test_build_request_sections(tmp_path: Path, monkeypatch) -> None:
    engine = NarrativeEngine()
    state = GameState(
        session_id="req-test",
        player=PlayerState(name="Test", location="e-rantel"),
        characters_active=[],
        situations=["fumo all'orizzonte"],
    )
    # avoid touching real saves: stub recent chat empty via fake session id + empty file
    from app.services import save_manager

    sm = save_manager.SaveManager(root=tmp_path / "saves")
    engine.saves = sm
    sm.save_game_state(state)
    (tmp_path / "saves" / state.session_id / "chat.jsonl").write_text("", encoding="utf-8")

    req = engine.build_request(state=state, user_message="guardo intorno")
    assert isinstance(req, NarrativeRequest)
    assert req.canon_facts.location == "e-rantel"
    assert "fumo all'orizzonte" in req.canon_facts.situations
    assert req.player_action == "guardo intorno"
    payload = req.model_dump()
    assert "canon_facts" in payload
    assert "world_pages" in payload
    assert "chat_recent" in payload
    assert "character_cards" in payload
