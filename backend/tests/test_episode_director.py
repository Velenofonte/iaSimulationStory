"""Tests for EpisodeDirector contextual rolls."""

from app.config import settings
from app.models import GameState, PlayerState
from app.models.game_state import EpisodeRuntime, NotorietyRuntime
from app.services.episode_director import EpisodeDirector
from app.services.episode_pack import default_episode_pack, parse_episode_pack


def _state(**kwargs) -> GameState:
    state = GameState(
        session_id=kwargs.pop("session_id", "sess-1"),
        story_id="overlord",
        player=PlayerState(location=kwargs.pop("location", "avamposto-bosco-silente")),
        characters_active=kwargs.pop("characters_active", []),
        situations=kwargs.pop("situations", []),
        episode=EpisodeRuntime(
            turn_index=kwargs.pop("turn_index", 0),
            turns_since_event=kwargs.pop("turns_since_event", 5),
            last_tier=kwargs.pop("last_tier", 0),
            recent_kinds=kwargs.pop("recent_kinds", []),
            last_beat_turn=kwargs.pop("last_beat_turn", None),
            last_stance=kwargs.pop("last_stance", ""),
            consecutive_events=kwargs.pop("consecutive_events", 0),
        ),
        notoriety=NotorietyRuntime(
            score=kwargs.pop("score", 0),
            labels=kwargs.pop("labels", []),
        ),
        minutes=kwargs.pop("minutes", 10 * 60),
        time=kwargs.pop("time", "Giorno 1 · mattina · 10:00"),
    )
    return state


def test_beat_imminent_suppresses_episode() -> None:
    director = EpisodeDirector(pack=default_episode_pack())
    ep = director.decide(
        _state(),
        stance="wait",
        location_meta={"kind": "outpost", "danger": "medium"},
        beat_imminent=True,
    )
    assert ep is None


def test_seed_is_deterministic() -> None:
    pack = default_episode_pack()
    director = EpisodeDirector(pack=pack)
    a = director.decide(
        _state(turn_index=7, turns_since_event=6),
        stance="wait",
        location_meta={"kind": "wilderness", "danger": "high"},
    )
    b = director.decide(
        _state(turn_index=7, turns_since_event=6),
        stance="wait",
        location_meta={"kind": "wilderness", "danger": "high"},
    )
    if a is None and b is None:
        return
    assert a is not None and b is not None
    assert a.tier == b.tier
    assert a.kind == b.kind


def test_wait_reduces_t0_vs_dialogue(monkeypatch) -> None:
    # Force a pack that still has some T0 but wait should fire more often.
    pack = parse_episode_pack(
        {
            "location_kinds": {"outpost": [40, 20, 15, 10, 8, 5, 2]},
            "modifiers": {
                "stance_wait": [0.05, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5],
                "stance_dialogue": [5.0, 2.0, 0.2, 0.1, 0.05, 0.02, 0.01],
            },
        }
    )
    director = EpisodeDirector(pack=pack)
    wait_hits = 0
    dialogue_hits = 0
    for i in range(40):
        w = director.decide(
            _state(session_id=f"w-{i}", turn_index=i, turns_since_event=4),
            stance="wait",
            location_meta={"kind": "outpost"},
        )
        d = director.decide(
            _state(session_id=f"d-{i}", turn_index=i, turns_since_event=4),
            stance="dialogue",
            location_meta={"kind": "outpost"},
        )
        if w is not None:
            wait_hits += 1
        if d is not None:
            dialogue_hits += 1
    assert wait_hits > dialogue_hits


def test_no_consecutive_high_tiers() -> None:
    pack = parse_episode_pack(
        {
            "location_kinds": {"wilderness": [0, 0, 0, 0, 0, 50, 50]},
            "modifiers": {"cooldown": [1, 1, 1, 1, 1, 1, 1]},
        }
    )
    director = EpisodeDirector(pack=pack)
    state = _state(last_tier=5, turns_since_event=0, turn_index=3)
    ep = director.decide(
        state,
        stance="wait",
        location_meta={"kind": "wilderness", "danger": "high"},
    )
    assert ep is None


def test_cooldown_after_high_tier(monkeypatch) -> None:
    monkeypatch.setattr(settings, "episode_cooldown_turns", 3)
    pack = parse_episode_pack(
        {
            "location_kinds": {"road": [10, 10, 10, 10, 20, 20, 20]},
            "modifiers": {
                "cooldown": [10, 1, 0.1, 0.1, 0.05, 0.01, 0.01],
                "stance_wait": [1, 1, 1, 1, 1, 1, 1],
            },
        }
    )
    director = EpisodeDirector(pack=pack)
    high = 0
    for i in range(30):
        ep = director.decide(
            _state(
                session_id=f"c-{i}",
                turn_index=i,
                last_tier=5,
                turns_since_event=1,
            ),
            stance="wait",
            location_meta={"kind": "road"},
        )
        if ep and ep.tier >= 5:
            high += 1
    assert high < 8


def test_recent_kind_does_not_repeat() -> None:
    pack = parse_episode_pack(
        {
            "location_kinds": {"road": [0, 0, 0, 0, 100, 0, 0]},
            "modifiers": {
                "stance_wait": [1, 1, 1, 1, 1, 1, 1],
                "quiet_streak": [1, 1, 1, 1, 1, 1, 1],
            },
        }
    )
    director = EpisodeDirector(pack=pack)
    for i in range(25):
        ep = director.decide(
            _state(
                session_id=f"r-{i}",
                turn_index=i,
                turns_since_event=3,
                recent_kinds=["social", "threat"],
            ),
            stance="wait",
            location_meta={"kind": "road"},
        )
        assert ep is not None
        # Both of the last two kinds stay barred, so a motif cannot alternate back in.
        assert ep.kind not in {"threat", "social"}


def test_light_tier_also_cools_down() -> None:
    pack = parse_episode_pack(
        {
            "location_kinds": {"outpost": [0, 0, 100, 0, 0, 0, 0]},
            "modifiers": {
                "cooldown": [1, 0, 0, 0, 0, 0, 0],
                "stance_wait": [1, 1, 1, 1, 1, 1, 1],
                "quiet_streak": [1, 1, 1, 1, 1, 1, 1],
                "baseline_calm": [1, 0, 1, 1, 1, 1, 1],
            },
        }
    )
    director = EpisodeDirector(pack=pack)
    state = _state(last_tier=2, turns_since_event=0, turn_index=4)
    assert director.decide(state, stance="wait", location_meta={"kind": "outpost"}) is None


def test_never_samples_tier_1() -> None:
    pack = parse_episode_pack(
        {
            "location_kinds": {"road": [10, 80, 10, 0, 0, 0, 0]},
            "modifiers": {
                "baseline_calm": [1, 1, 1, 1, 1, 1, 1],
                "stance_wait": [1, 1, 1, 1, 1, 1, 1],
                "quiet_streak": [1, 1, 1, 1, 1, 1, 1],
            },
        }
    )
    director = EpisodeDirector(pack=pack)
    for i in range(200):
        ep = director.decide(
            _state(session_id=f"t1-{i}", turn_index=i, turns_since_event=5),
            stance="wait",
            location_meta={"kind": "road"},
        )
        if ep is not None:
            assert ep.tier != 1


def test_pending_thread_gates_new_openings() -> None:
    pack = parse_episode_pack(
        {"location_kinds": {"wilderness": [1, 0, 30, 30, 20, 10, 9]}}
    )
    director = EpisodeDirector(pack=pack)
    state = _state(
        situations=["Messaggio del Vuoto incompiuto"],
        turns_since_event=5,
        consecutive_events=0,
    )
    for i in range(30):
        state.episode.turn_index = i
        assert (
            director.decide(state, stance="wait", location_meta={"kind": "wilderness"})
            is None
        )


def test_repeated_wait_damps_openings() -> None:
    pack = parse_episode_pack({"location_kinds": {"outpost": [40, 20, 15, 10, 8, 5, 2]}})
    director = EpisodeDirector(pack=pack)
    first = 0
    repeat = 0
    for i in range(40):
        if director.decide(
            _state(session_id=f"f-{i}", turn_index=i, turns_since_event=4),
            stance="wait",
            location_meta={"kind": "outpost"},
        ):
            first += 1
        if director.decide(
            _state(
                session_id=f"f-{i}",
                turn_index=i,
                turns_since_event=4,
                last_stance="wait",
            ),
            stance="wait",
            location_meta={"kind": "outpost"},
        ):
            repeat += 1
    assert repeat < first


def test_pileup_guard_caps_consecutive_events() -> None:
    pack = parse_episode_pack(
        {
            "location_kinds": {"wilderness": [1, 0, 30, 30, 20, 10, 9]},
            "modifiers": {"baseline_calm": [1, 0, 1, 1, 1, 1, 1]},
        }
    )
    director = EpisodeDirector(pack=pack)
    state = _state(turn_index=0, turns_since_event=3)
    streak = 0
    worst = 0
    for _ in range(60):
        state.situations = []
        ep = director.decide(state, stance="action", location_meta={"kind": "wilderness"})
        streak = streak + 1 if ep else 0
        worst = max(worst, streak)
        EpisodeDirector.record_outcome(state, ep, stance="action")
    assert worst <= 2


def test_record_outcome_updates_runtime() -> None:
    state = _state(turn_index=2, turns_since_event=4)
    from app.models.narrative import Episode

    EpisodeDirector.record_outcome(
        state,
        Episode(tier=3, tier_label="frizione", kind="social", exposure="low"),
    )
    assert state.episode.turn_index == 3
    assert state.episode.turns_since_event == 0
    assert state.episode.last_tier == 3
    assert state.episode.recent_kinds[-1] == "social"


def test_disabled_engine_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(settings, "episode_engine_enabled", False)
    director = EpisodeDirector(pack=default_episode_pack())
    assert (
        director.decide(
            _state(),
            stance="wait",
            location_meta={"kind": "wilderness"},
        )
        is None
    )
