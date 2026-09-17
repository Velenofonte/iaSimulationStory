"""Tests for notoriety score, decay, gap."""

from app.models import GameState, PlayerState
from app.models.game_state import DeedRecord, NotorietyRuntime
from app.services.episode_pack import default_episode_pack
from app.services.notoriety import (
    apply_deed,
    decay,
    format_wiki_section,
    gap,
    to_prompt_slice,
)


def _state() -> GameState:
    return GameState(
        session_id="s",
        player=PlayerState(name="Rayan", character_id="rayan"),
        notoriety=NotorietyRuntime(),
        day=5,
    )


def test_apply_deed_increases_score_with_witnesses() -> None:
    pack = default_episode_pack()
    state = _state()
    apply_deed(
        state,
        DeedRecord(
            id="save_merchant",
            summary="Salva un mercante dai banditi",
            scale="D",
            witnesses=["civilian", "merchant"],
            attributed=True,
            beneficiary="merchant",
        ),
        pack,
    )
    assert state.notoriety.score > 0
    assert state.notoriety.reach in {"city", "region", "local"}
    assert any(d.id == "save_merchant" for d in state.notoriety.deeds)


def test_unattributed_feeds_legend_only() -> None:
    pack = default_episode_pack()
    state = _state()
    apply_deed(
        state,
        DeedRecord(
            id="crater",
            summary="Una collina sparisce",
            scale="100+",
            witnesses=["civilian"],
            attributed=False,
            evidence="cratere",
            beneficiary="none",
        ),
        pack,
    )
    assert state.notoriety.score == 0
    assert state.notoriety.legend_score > 0
    assert state.notoriety.deeds[0].persistent is True


def test_decay_spares_persistent_evidence() -> None:
    pack = default_episode_pack()
    state = _state()
    apply_deed(
        state,
        DeedRecord(
            id="crater",
            summary="Cratere",
            scale="A++",
            witnesses=["guard"],
            attributed=True,
            evidence="cratere",
        ),
        pack,
    )
    before = state.notoriety.score
    decay(state, pack, days=10)
    # Soft decay only when persistent evidence present.
    assert state.notoriety.score >= before * 0.5


def test_gap_between_deeds_and_label() -> None:
    pack = default_episode_pack()
    state = _state()
    state.notoriety.labels = ["copper"]
    apply_deed(
        state,
        DeedRecord(
            id="big",
            summary="Impresa A++",
            scale="A++",
            witnesses=["officer", "priest"],
            attributed=True,
            beneficiary="nation",
        ),
        pack,
    )
    assert gap(state, pack) >= 2


def test_prompt_slice_and_wiki_lines() -> None:
    pack = default_episode_pack()
    state = _state()
    apply_deed(
        state,
        DeedRecord(
            id="x",
            summary="Fatto utile",
            scale="C",
            witnesses=["adventurer"],
            attributed=True,
        ),
        pack,
    )
    slice_text = to_prompt_slice(state, pack)
    assert "Notorieta" in slice_text
    assert "score=" in slice_text
    lines = format_wiki_section(state, pack)
    assert any("Impresa" in line or "Portata" in line for line in lines)
