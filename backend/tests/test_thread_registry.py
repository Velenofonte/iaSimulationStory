"""Tests for narrative thread registry (situations derive / exit / cap)."""

from app.models import GameState, PlayerState
from app.models.game_state import NpcKnowledgeFact
from app.models.narrative import Episode, NarrativeTime
from app.models.turn import TurnResolution
from app.services.thread_registry import (
    SITUATIONS_CAP,
    derive_situations,
    ensure_exit_threads,
    ensure_pending_threads,
    is_exit_intent,
)


def _state(**kwargs) -> GameState:
    return GameState(
        session_id="s",
        player=PlayerState(location=kwargs.pop("location", "avamposto")),
        situations=kwargs.pop("situations", []),
    )


def _resolution(**kwargs) -> TurnResolution:
    return TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=2),
        scene_brief=kwargs.pop("scene_brief", ["un delta"]),
        situations_add=kwargs.pop("situations_add", []),
        situations_remove=kwargs.pop("situations_remove", []),
        present_join=kwargs.pop("present_join", []),
        location=kwargs.pop("location", None),
    )


def test_derive_from_episode_tier_ge_2() -> None:
    ep = Episode(tier=3, tier_label="frizione", kind="arrival", opens_thread=True)
    derived = derive_situations(_resolution(), ep, _state())
    assert any("arrival" in s.summary and "frizione" in s.summary for s in derived)
    assert all(s.id for s in derived)


def test_derive_from_present_join() -> None:
    derived = derive_situations(
        _resolution(present_join=["figura_incappucciata"], scene_brief=["consegna un oggetto"]),
        None,
        _state(),
    )
    assert any("figura_incappucciata" in s.summary for s in derived)
    assert any(s.id.startswith("present_") for s in derived)


def test_ensure_skips_when_already_populated() -> None:
    res = _resolution(situations_add=["gia presente"])
    out = ensure_pending_threads(
        res,
        Episode(tier=4, tier_label="complicazione", kind="mystery"),
        _state(),
    )
    assert len(out.situations_add) == 1
    assert out.situations_add[0].summary == "gia presente"


def test_ensure_derives_when_empty() -> None:
    out = ensure_pending_threads(
        _resolution(situations_add=[]),
        Episode(tier=2, tier_label="gancio", kind="discovery", opens_thread=True),
        _state(location="bosco"),
    )
    assert out.situations_add
    assert "discovery" in out.situations_add[0].summary
    assert out.situations_add[0].id.startswith("episode_")


def test_cap_triggers_remove_oldest() -> None:
    state = _state(
        situations=[
            NpcKnowledgeFact(id=f"filo-{i}", summary=f"filo-{i}")
            for i in range(SITUATIONS_CAP)
        ]
    )
    out = ensure_pending_threads(
        _resolution(situations_add=["nuovo filo"]),
        None,
        state,
    )
    assert any(s.summary == "nuovo filo" for s in out.situations_add)
    assert out.situations_remove
    assert out.situations_remove[0].startswith("filo-")


def test_clip_keeps_word_boundary() -> None:
    from app.services.thread_registry import _clip

    long = "Figura incappucciata lascia un medaglione misterioso nel bosco silente vicino all'avamposto"
    out = _clip(long, 40)
    assert out.endswith("…")
    assert " " not in out[-2:]  # not cut mid-token before ellipsis
    assert len(out) <= 40


def test_exit_intent_detection() -> None:
    assert is_exit_intent("Bhe vado", location_changed=False)
    assert is_exit_intent("mi incammino verso E-Rantel", location_changed=False)
    assert is_exit_intent("guardo", location_changed=True)
    assert not is_exit_intent("guardo il medaglione", location_changed=False)


def test_exit_defers_open_situations() -> None:
    state = _state(
        situations=[
            NpcKnowledgeFact(id="messaggio_vuoto", summary="Messaggio del Vuoto incompiuto")
        ]
    )
    out = ensure_exit_threads(
        _resolution(),
        player_action="Bhe vado",
        previous_location="avamposto",
        state=state,
    )
    assert out.situations_remove == []
    assert any(s.id == "messaggio_vuoto" for s in out.situations_add)
    assert any("In sospeso" in s.summary for s in out.situations_add)
