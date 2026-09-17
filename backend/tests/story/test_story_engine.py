"""Tests for StoryEngine: arc close, pressures, stall, chain, canon guard."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.config import settings
from app.models import GameState, PlayerState
from app.models.game_state import FrontRuntime
from app.services.era_loader import EraLoader
from app.services.front_engine import FrontEngine
from app.services.front_loader import FrontLoader, parse_front_dict
from app.services.story_engine import StoryEngine
from app.services.wiki_writer import WikiWriter


def _write_front(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _mini_chain(tmp_path: Path) -> tuple[Path, Path]:
    fronts_dir = tmp_path / "fronts"
    fronts_dir.mkdir()
    eras_dir = tmp_path / "eras"
    eras_dir.mkdir()
    a = {
        "id": "arc_a",
        "name": "A",
        "start": {"day": 1, "minutes": 480, "beat": "a1"},
        "flags_initial": {"ok": True},
        "intents_layer3": [
            {"id": "pressure_x", "summary": "spinta X", "entities": ["x"]}
        ],
        "beats": [
            {
                "id": "a1",
                "title": "Start",
                "place": "town",
                "hours_after_previous": 0,
                "prereq": {"all": ["ok"]},
                "cast_in_world": [],
                "scene_canon": "Inizio.\n",
                "on_fire": {"marks": ["a1_done"]},
            },
            {
                "id": "a2",
                "title": "End",
                "place": "town",
                "hours_after_previous": 1,
                "prereq": {"all": ["a1_done"]},
                "cast_in_world": [],
                "scene_canon": "Fine A.\n",
                "on_fire": {"marks": ["a_done"]},
                "resolves_arc": "weak",
            },
        ],
        "on_close": {
            "weak": {
                "world_flags": {"gate_open": True},
                "chronicle": [
                    {
                        "id": "a_closed",
                        "reach": "world",
                        "summary": "Arco A chiuso.",
                    }
                ],
            },
            "broken": {
                "world_flags": {"gate_open": False},
                "chronicle": [
                    {
                        "id": "a_broken",
                        "reach": "local",
                        "summary": "Arco A spezzato.",
                    }
                ],
            },
            "lapsed": {
                "world_flags": {"gate_open": False},
                "chronicle": [
                    {"id": "a_lapsed", "reach": "local", "summary": "Arco A scaduto."}
                ],
            },
        },
    }
    b = {
        "id": "arc_b",
        "name": "B",
        "start": {
            "day": 1,
            "minutes": 480,
            "beat": "b1",
            "relative_to": "previous_arc_close",
        },
        "flags_initial": {},
        "beats": [
            {
                "id": "b1",
                "title": "Next",
                "place": "town",
                "hours_after_previous": 0,
                "prereq": {"all": []},
                "cast_in_world": [],
                "scene_canon": "Successore.\n",
                "on_fire": {"marks": ["b1_done"]},
                "resolves_arc": "weak",
            }
        ],
        "on_close": {
            "weak": {
                "chronicle": [
                    {"id": "b_closed", "reach": "world", "summary": "Arco B chiuso."}
                ]
            }
        },
    }
    _write_front(fronts_dir / "arc_a.yaml", a)
    _write_front(fronts_dir / "arc_b.yaml", b)
    era = {
        "id": "test_era",
        "name": "Test Era",
        "start": {"day": 1, "minutes": 480, "location": "town"},
        "entry_arc": "arc_a",
        "arc_sequence": [
            {
                "id": "arc_a",
                "next": [
                    {
                        "arc": "arc_b",
                        "when_outcome": ["canon", "weak", "diverted"],
                        "requires_flags": {"gate_open": True},
                    }
                ],
            },
            {"id": "arc_b", "next": []},
        ],
        "world_flags": {},
        "chronicle": [],
        "insiders": [],
    }
    (eras_dir / "test_era.yaml").write_text(
        yaml.safe_dump(era, allow_unicode=True), encoding="utf-8"
    )
    return fronts_dir, eras_dir


def _engine(fronts_dir: Path, eras_dir: Path, wiki_dir: Path) -> tuple[FrontEngine, StoryEngine]:
    wiki = WikiWriter(wiki_dir=wiki_dir)
    loader = FrontLoader(fronts_dir=fronts_dir)
    fronts = FrontEngine(loader=loader, wiki=wiki)
    story = StoryEngine(
        fronts=fronts,
        wiki=wiki,
        era_loader=EraLoader(story_id="overlord", eras_path=eras_dir),
        front_loader=loader,
    )
    fronts.story = story
    return fronts, story


def test_close_canon_applies_on_close_and_chains(tmp_path: Path):
    fronts_dir, eras_dir = _mini_chain(tmp_path)
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    fronts, story = _engine(fronts_dir, eras_dir, wiki_dir)
    state = GameState(
        session_id="t",
        player=PlayerState(name="P", location="elsewhere"),
    )
    story.seed_era(state, "test_era", activate_entry=True, fire_start=False)
    # Jump past both beats of arc_a
    state.day = 1
    state.minutes = 480 + 60
    fronts.tick(state, 0, hydrate_scene=False)
    assert any(r.arc_id == "arc_a" for r in state.story.arcs)
    record = state.story.arcs[-1]
    assert record.outcome == "weak"
    assert state.story.world_flags.get("gate_open") is True
    assert state.story.current_arc == "arc_b"
    assert "arc_b" in state.fronts
    # Clock must not rewind
    assert state.day == 1
    assert state.minutes >= 480


def test_broken_records_pressures(tmp_path: Path):
    fronts_dir, eras_dir = _mini_chain(tmp_path)
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    fronts, story = _engine(fronts_dir, eras_dir, wiki_dir)
    state = GameState(
        session_id="t",
        player=PlayerState(name="P", location="town"),
    )
    story.seed_era(state, "test_era", activate_entry=True, fire_start=False)
    runtime = state.fronts["arc_a"]
    runtime.status = "interrupted"
    runtime.interrupted_at_day = state.day
    # Force close as broken without waiting stall
    story.on_arc_closed(state, "arc_a", forced_outcome="broken")
    assert state.story.arcs[-1].outcome == "broken"
    assert any(p.id == "pressure_x" for p in state.story.pressures)
    # Canon guard: gate_open false → no arc_b
    assert state.story.current_arc is None
    assert "arc_b" not in state.fronts or state.fronts["arc_b"].status != "active"


def test_requires_flags_block_successor(tmp_path: Path):
    fronts_dir, eras_dir = _mini_chain(tmp_path)
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    _, story = _engine(fronts_dir, eras_dir, wiki_dir)
    state = GameState(
        session_id="t",
        player=PlayerState(name="P", location="town"),
    )
    story.seed_era(state, "test_era", activate_entry=True, fire_start=False)
    state.fronts["arc_a"].status = "resolved"
    state.fronts["arc_a"].last_fired_beat = "a2"
    # Close without on_close weak flags
    story.on_arc_closed(state, "arc_a", forced_outcome="broken", skip_advance=False)
    assert "arc_b" not in state.fronts or state.story.current_arc != "arc_b"


def test_stall_closes_active_as_lapsed(tmp_path: Path, monkeypatch):
    fronts_dir, eras_dir = _mini_chain(tmp_path)
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    fronts, story = _engine(fronts_dir, eras_dir, wiki_dir)
    monkeypatch.setattr(settings, "stall_after_days", 1)
    state = GameState(
        session_id="t",
        player=PlayerState(name="P", location="elsewhere"),
    )
    story.seed_era(state, "test_era", activate_entry=True, fire_start=False)
    runtime = state.fronts["arc_a"]
    runtime.accumulated_minutes = 1440
    closed = story.check_stall(state)
    assert "arc_a" in closed
    assert state.story.arcs[-1].outcome == "lapsed"


def test_stall_closes_interrupted_as_broken(tmp_path: Path, monkeypatch):
    fronts_dir, eras_dir = _mini_chain(tmp_path)
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    fronts, story = _engine(fronts_dir, eras_dir, wiki_dir)
    monkeypatch.setattr(settings, "stall_after_days", 1)
    state = GameState(
        session_id="t",
        player=PlayerState(name="P", location="elsewhere"),
    )
    story.seed_era(state, "test_era", activate_entry=True, fire_start=False)
    runtime = state.fronts["arc_a"]
    runtime.status = "interrupted"
    runtime.interrupted_at_day = state.day - 2
    closed = story.check_stall(state)
    assert "arc_a" in closed
    assert state.story.arcs[-1].outcome == "broken"


def test_parse_on_close_from_hk_invasion():
    path = settings.fronts_dir / "hk_invasion.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    definition = parse_front_dict(data)
    assert "canon" in definition.on_close
    assert definition.on_close["canon"].world_flags.get("holy_kingdom_south_fallen") is True
    assert definition.start_relative_to == "previous_arc_close"
    assert definition.start_beat == "wall_garrison"
    wall = definition.beat_by_id["wall_garrison"]
    assert wall.place == "great-wall"
    assert "remedios" not in wall.cast_in_world
    assert "pabel" in wall.cast_in_world
    assert wall.ambient
    assert definition.beat_by_id["kalinsha_council"].place == "kalinsha"
    assert "remedios" in definition.beat_by_id["kalinsha_council"].cast_in_world


def test_hk_embassy_visits_re_estize_before_erantel():
    path = settings.fronts_dir / "hk_embassy.yaml"
    definition = parse_front_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = [b.id for b in definition.beats]
    assert ids.index("re_estize_refusal") < ids.index("arrive_erantel")
    assert definition.beat_by_id["re_estize_refusal"].place == "re-estize"


def test_build_story_slice_hides_secrets():
    from app.models.game_state import ChronicleEntry

    state = GameState(
        session_id="t",
        story_id="overlord",
        player=PlayerState(name="Rayan", location="hoburns", character_id="rayan"),
    )
    state.story.era = "holy_kingdom"
    state.story.chronicle = [
        ChronicleEntry(
            id="pub", summary="pubblico", reach="world", source="canon_digest"
        ),
        ChronicleEntry(
            id="sec",
            summary="SEGRETO_JALDABAOTH",
            reach="none",
            secret=True,
            source="canon_digest",
        ),
    ]
    story = StoryEngine(era_loader=EraLoader(story_id="overlord"))
    slice_text = story.build_story_slice(state)
    assert "pubblico" in slice_text
    assert "SEGRETO_JALDABAOTH" not in slice_text
