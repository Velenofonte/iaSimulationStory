"""Tests for thread stall detection (non-coercive advance/close hint)."""

from app.models.narrative import NarrativeChatTurn
from app.services.thread_stall import detect_thread_stall


def _users(*msgs: str) -> list[NarrativeChatTurn]:
    return [NarrativeChatTurn(role="user", content=m) for m in msgs]


def test_medaglione_streak_yields_non_coercive_hint() -> None:
    chat = _users(
        "Esamino il medaglione",
        "Provo ad attivare il medaglione",
    )
    hint = detect_thread_stall(chat, "Fornisco energia al medaglione", [])
    assert hint
    assert "non e' obbligatorio chiudere" in hint
    assert "medaglione" in hint


def test_different_topics_yield_no_hint() -> None:
    chat = _users("Parlo con Harn", "Apro la cassa")
    assert detect_thread_stall(chat, "Guardo il cielo", []) == ""


def test_tracked_situation_softens_note() -> None:
    chat = _users(
        "Tocco il medaglione",
        "Scuoto il medaglione",
    )
    hint = detect_thread_stall(
        chat,
        "Esamino di nuovo il medaglione",
        ["Messaggio del medaglione incompiuto"],
    )
    assert hint
    assert "compare in situations" in hint


def test_below_threshold_is_empty() -> None:
    chat = _users("Guardo il medaglione")
    assert detect_thread_stall(chat, "Tocco il medaglione", [], threshold=3) == ""
