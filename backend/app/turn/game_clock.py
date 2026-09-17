"""Game clock: day + minutes as sole source of truth for in-world time."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import GameState

DAWN_MINUTES = 6 * 60  # 06:00
DEFAULT_DAY = 1
DEFAULT_MINUTES = 8 * 60  # 08:00

# (min_inclusive, max_inclusive) — LLM picks minutes inside the range; code clamps.
# Sized so a few media/lunga (or un riposo) can reach day-scale arc beats.
BUCKET_RANGES: dict[str, tuple[int, int]] = {
    "istantanea": (1, 15),
    "breve": (20, 120),
    "media": (120, 360),
    "lunga": (360, 1440),
}

VALID_BUCKETS = frozenset({*BUCKET_RANGES.keys(), "riposo"})
DEFAULT_BUCKET = "istantanea"

_BUCKET_ALIASES = {
    "short": "breve",
    "instant": "istantanea",
    "instantaneous": "istantanea",
    "quick": "istantanea",
    "medium": "media",
    "long": "lunga",
    "rest": "riposo",
    "sleep": "riposo",
}


def phase_of(minutes: int) -> str:
    m = minutes % (24 * 60)
    if 6 * 60 <= m < 12 * 60:
        return "mattina"
    if 12 * 60 <= m < 18 * 60:
        return "pomeriggio"
    if 18 * 60 <= m < 22 * 60:
        return "sera"
    return "notte"


def format_clock(minutes: int) -> str:
    m = minutes % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def format_label(day: int, minutes: int) -> str:
    return f"Giorno {day} · {phase_of(minutes)} · {format_clock(minutes)}"


def normalize_bucket(raw: str | None) -> str:
    if not raw:
        return DEFAULT_BUCKET
    key = raw.strip().lower()
    key = _BUCKET_ALIASES.get(key, key)
    if key in VALID_BUCKETS:
        return key
    return DEFAULT_BUCKET


def default_minutes_for(bucket: str) -> int:
    kind = normalize_bucket(bucket)
    if kind == "riposo":
        return 0
    lo, hi = BUCKET_RANGES[kind]
    return (lo + hi) // 2


def clamp_minutes(bucket: str, minutes: int | None) -> int:
    kind = normalize_bucket(bucket)
    if kind == "riposo":
        return 0
    lo, hi = BUCKET_RANGES[kind]
    if minutes is None:
        return default_minutes_for(kind)
    return max(lo, min(hi, int(minutes)))


def minutes_until_next_dawn(minutes: int) -> int:
    """Minutes from current clock time until next day's dawn (riposo semantics)."""
    m = int(minutes) % (24 * 60)
    return (24 * 60 - m) + DAWN_MINUTES


def sync_time_label(state: GameState) -> None:
    state.time = format_label(state.day, state.minutes)


def advance_by_minutes(state: GameState, delta: int) -> int:
    """Advance clock by an explicit minute delta. Returns minutes applied."""
    applied = max(0, int(delta))
    total = state.minutes + applied
    state.day += total // (24 * 60)
    state.minutes = total % (24 * 60)
    sync_time_label(state)
    return applied


def advance_from_parts(
    state: GameState,
    bucket: str | None,
    minutes: int | None,
) -> tuple[str, int]:
    """Advance clock from structured NarrativeReply.time fields."""
    kind = normalize_bucket(bucket)
    if kind == "riposo":
        return _apply_advance(state, kind, None)
    return _apply_advance(state, kind, minutes)


def planned_delta_minutes(
    state: GameState,
    bucket: str | None,
    minutes: int | None,
) -> tuple[str, int]:
    """Compute how many minutes a bucket would advance, without mutating state."""
    kind = normalize_bucket(bucket)
    if kind == "riposo":
        return kind, minutes_until_next_dawn(state.minutes)
    return kind, clamp_minutes(kind, minutes)


def _apply_advance(
    state: GameState,
    kind: str,
    requested: int | None,
) -> tuple[str, int]:
    if kind == "riposo":
        delta = minutes_until_next_dawn(state.minutes)
        state.day += 1
        state.minutes = DAWN_MINUTES
        sync_time_label(state)
        return kind, delta

    delta = clamp_minutes(kind, requested)
    advance_by_minutes(state, delta)
    return kind, delta


def ensure_clock_fields(state: GameState) -> bool:
    """Fill missing day/minutes on legacy saves. Returns True if mutated."""
    changed = False
    if getattr(state, "day", None) is None:
        state.day = DEFAULT_DAY
        changed = True
    if getattr(state, "minutes", None) is None:
        state.minutes = DEFAULT_MINUTES
        changed = True
    if state.minutes < 0 or state.minutes >= 24 * 60:
        state.minutes = state.minutes % (24 * 60)
        changed = True
    label = format_label(state.day, state.minutes)
    if state.time != label:
        state.time = label
        changed = True
    return changed
