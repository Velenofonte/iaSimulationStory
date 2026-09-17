"""Tests for game clock advancement."""

from app.models import GameState, PlayerState
from app.services.game_clock import (
    DAWN_MINUTES,
    advance_from_parts,
    clamp_minutes,
    ensure_clock_fields,
    format_clock,
    format_label,
    normalize_bucket,
    phase_of,
)


def test_phase_boundaries() -> None:
    assert phase_of(6 * 60) == "mattina"
    assert phase_of(12 * 60) == "pomeriggio"
    assert phase_of(18 * 60) == "sera"
    assert phase_of(22 * 60) == "notte"
    assert phase_of(3 * 60) == "notte"


def test_format_helpers() -> None:
    assert format_clock(480) == "08:00"
    assert format_label(1, 480) == "Giorno 1 · mattina · 08:00"
    assert format_label(2, 14 * 60 + 30) == "Giorno 2 · pomeriggio · 14:30"


def test_normalize_bucket() -> None:
    assert normalize_bucket(None) == "istantanea"
    assert normalize_bucket("BREVE") == "breve"
    assert normalize_bucket("nope") == "istantanea"


def test_clamp_minutes() -> None:
    assert clamp_minutes("istantanea", 3) == 3
    assert clamp_minutes("istantanea", 99) == 15
    assert clamp_minutes("istantanea", 0) == 1
    assert clamp_minutes("breve", None) == 70  # midpoint 20..120


def test_advance_with_llm_minutes() -> None:
    state = GameState(session_id="t", day=1, minutes=480)
    kind, delta = advance_from_parts(state, "istantanea", 7)
    assert kind == "istantanea"
    assert delta == 7
    assert state.minutes == 487


def test_advance_wrap_midnight() -> None:
    state = GameState(session_id="t", day=1, minutes=23 * 60 + 50)  # 23:50
    advance_from_parts(state, "breve", 45)  # +45 -> 00:35 day 2
    assert state.day == 2
    assert state.minutes == 35
    assert state.time == "Giorno 2 · notte · 00:35"


def test_advance_riposo_to_next_dawn() -> None:
    state = GameState(session_id="t", day=1, minutes=22 * 60)  # 22:00
    kind, delta = advance_from_parts(state, "riposo", None)
    assert kind == "riposo"
    assert delta == 8 * 60  # 22:00 → 06:00 next day
    assert state.day == 2
    assert state.minutes == DAWN_MINUTES
    assert state.time == "Giorno 2 · mattina · 06:00"


def test_advance_missing_tag_uses_midpoint() -> None:
    state = GameState(session_id="t", day=1, minutes=480)
    kind, delta = advance_from_parts(state, None, None)
    assert kind == "istantanea"
    assert delta == 8  # midpoint 1..15
    assert state.minutes == 488


def test_ensure_clock_fields_syncs_label() -> None:
    state = GameState(
        session_id="t",
        day=1,
        minutes=480,
        time="morning, day 1",
        player=PlayerState(),
    )
    assert ensure_clock_fields(state) is True
    assert state.time == "Giorno 1 · mattina · 08:00"


def test_ensure_clock_fields_keeps_day_zero() -> None:
    state = GameState(session_id="t", day=0, minutes=0, time="")
    ensure_clock_fields(state)
    assert state.day == 0
    assert state.minutes == 0
