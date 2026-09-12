"""Tests for arc front engine (watch path + impacts)."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import yaml

from app.models import FrontRuntime, GameState, PlayerState
from app.models.reviews import FrontImpact
from app.services.front_engine import FrontEngine, player_at_place
from app.services.front_loader import FrontLoader
from app.services.wiki_writer import WikiWriter


MINI_FRONT = {
    "id": "test_arc",
    "name": "Test Arc",
    "start": {"day": 1, "minutes": 480, "beat": "beat_a"},
    "temporal_constraints": ["Il titolo futuro non e' ancora valido."],
    "flags_initial": {"village_intact": True, "raid_done": False},
    "cast": {
        "hero": {
            "wiki": "hero",
            "role": "locale",
            "appear_from": "beat_a",
            "default_location": "village",
        },
        "later_npc": {
            "wiki": "later_npc",
            "role": "late",
            "appear_from": "beat_c",
            "default_location": "village",
        },
    },
    "intents_layer2": [{"id": "pressure_village", "summary": "pressure"}],
    "intents_layer3": [{"id": "ainz_foothold", "summary": "global"}],
    "beats": [
        {
            "id": "beat_a",
            "title": "Quiet",
            "place": "village",
            "hours_after_previous": 0,
            "prereq": {"all": ["village_intact"]},
            "cast_in_world": ["hero"],
            "scene_canon": "Il villaggio e' tranquillo.\nLa gente lavora i campi.\n",
            "on_fire": {
                "wiki_writes": [
                    {"entity": "village", "events_add": ["Quiet day at village."]}
                ],
                "marks": ["beat_a_done"],
            },
        },
        {
            "id": "beat_b",
            "title": "Rumors",
            "place": "village",
            "hours_after_previous": 2,
            "prereq": {"all": ["beat_a_done", "village_intact"], "none": ["raid_done"]},
            "cast_in_world": ["hero"],
            "scene_canon": "Circolano voci di armati.\n",
            "on_fire": {
                "wiki_writes": [
                    {"entity": "village", "events_add": ["Rumors of armed men."]}
                ],
                "marks": ["beat_b_done"],
            },
        },
        {
            "id": "beat_c",
            "title": "Raid",
            "place": "village",
            "hours_after_previous": 2,
            "prereq": {"all": ["beat_b_done", "village_intact"], "none": ["raid_done"]},
            "cast_in_world": ["hero", "later_npc"],
            "scene_canon": "Il villaggio e' sotto attacco.\n",
            "on_fire": {
                "wiki_writes": [
                    {"entity": "village", "events_add": ["Raid begins."]}
                ],
                "marks": ["raid_done", "beat_c_done"],
            },
        },
    ],
    "variants": [
        {
            "id": "destroyed",
            "replaces": ["beat_c"],
            "when": {"flag": "village_intact", "equals": False},
            "effect": "interrupt_default_queue",
            "note": "Village destroyed; raid skipped.",
        },
        {
            "id": "averted",
            "replaces": ["beat_c"],
            "when": {"flag": "raid_averted", "equals": True},
            "effect": "divert",
            "note": "Raid averted.",
        },
    ],
}


def _write_mini_world(tmp: Path) -> tuple[Path, Path]:
    fronts = tmp / "fronts"
    fronts.mkdir(parents=True)
    (fronts / "test_arc.yaml").write_text(
        yaml.safe_dump(MINI_FRONT, allow_unicode=True), encoding="utf-8"
    )
    wiki = tmp / "wiki"
    (wiki / "locations").mkdir(parents=True)
    (wiki / "characters").mkdir(parents=True)
    village = frontmatter.Post("# Village\n\n# Eventi\n\n", id="village", name="Village")
    (wiki / "locations" / "village.md").write_text(
        frontmatter.dumps(village), encoding="utf-8"
    )
    for cid, name in (("hero", "Hero"), ("later_npc", "Later")):
        post = frontmatter.Post(f"# {name}\n", id=cid, name=name, tier="minimal")
        (wiki / "characters" / f"{cid}.md").write_text(
            frontmatter.dumps(post), encoding="utf-8"
        )
    return fronts, wiki


def _engine(tmp: Path) -> FrontEngine:
    fronts_dir, wiki_dir = _write_mini_world(tmp)
    return FrontEngine(
        loader=FrontLoader(fronts_dir=fronts_dir),
        wiki=WikiWriter(wiki_dir=wiki_dir),
    )


def test_player_at_place_includes_local_outskirts() -> None:
    assert player_at_place("carne", "carne")
    assert player_at_place("carne", "carne_outskirts")
    assert not player_at_place("e-rantel", "carne")
    assert player_at_place("carne_village", "carne")
    assert player_at_place("Villaggio di Carne", "carne")
    assert player_at_place("Carne Village", "carne")


def test_front_exposes_temporal_context(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s", player=PlayerState(location="village"))
    engine.activate(state, "test_arc", fire_start=False)
    context = engine.build_temporal_context(state)
    assert "titolo futuro" in context
    assert "Vincoli temporali" in engine.build_prompt_slice(state)


def test_activate_fires_start_and_writes_wiki(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(
        session_id="s1",
        player=PlayerState(name="P", location="e-rantel"),
    )
    engine.activate(state, "test_arc")
    runtime = state.fronts["test_arc"]
    assert runtime.last_fired_beat == "beat_a"
    assert runtime.cursor_beat == "beat_b"
    assert runtime.flags["beat_a_done"] is True
    # PG absent → no hydrate
    assert state.situations == []
    wiki_body = (tmp_path / "wiki" / "locations" / "village.md").read_text(encoding="utf-8")
    assert "Quiet day at village." in wiki_body


def test_tick_fires_next_after_hours(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    fired = engine.tick(state, 0)
    assert fired == []
    assert state.fronts["test_arc"].last_fired_beat == "beat_a"
    # Absolute due for beat_b = start + 2h
    state.minutes = 480 + 60
    assert engine.tick(state, 0) == []
    state.minutes = 480 + 120
    fired = engine.tick(state, 0)
    assert fired == ["beat_b"]
    assert state.fronts["test_arc"].flags["beat_b_done"] is True
    assert state.fronts["test_arc"].last_fired_at_minutes == 600


def test_multi_tick_fires_in_order(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    state.minutes = 480 + 5 * 60  # past beat_c due
    fired = engine.tick(state, 0)
    assert fired == ["beat_b", "beat_c"]
    assert state.fronts["test_arc"].flags["raid_done"] is True


def test_absent_no_situations_present_hydrates(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    assert state.situations == []

    state2 = GameState(session_id="s2", player=PlayerState(location="village"))
    engine.activate(state2, "test_arc")
    assert any("tranquillo" in s.summary for s in state2.situations)
    assert "hero" in state2.characters_active


def test_prereq_fail_interrupts(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    state.fronts["test_arc"].flags["village_intact"] = False
    state.minutes = 480 + 120
    engine.tick(state, 0)
    assert state.fronts["test_arc"].status == "interrupted"
    assert state.fronts["test_arc"].last_fired_beat == "beat_a"


def test_variant_interrupt_on_raid_beat(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    state.minutes = 480 + 120
    engine.tick(state, 0)  # fire b
    state.fronts["test_arc"].flags["village_intact"] = False
    state.minutes = 480 + 240
    engine.tick(state, 0)  # would be c → variant interrupt
    assert state.fronts["test_arc"].status == "interrupted"
    assert state.fronts["test_arc"].last_fired_beat == "beat_b"
    wiki_body = (tmp_path / "wiki" / "locations" / "village.md").read_text(encoding="utf-8")
    assert "Raid begins." not in wiki_body


def test_prompt_slice_hides_later_cast(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    slice_text = engine.build_prompt_slice(state)
    assert "hero" in slice_text
    assert "later_npc" in slice_text  # listed as not yet
    assert "Non ancora in gioco" in slice_text
    cast_ids = engine.relevant_cast_wiki_ids(state)
    assert "hero" in cast_ids
    assert "later_npc" not in cast_ids


def test_front_impact_block_sets_flags(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    engine.apply_impacts(
        state,
        [
            FrontImpact(
                front_id="test_arc",
                intent_id="pressure_village",
                effect="block",
                evidence="il PG brucia il villaggio",
                flags_set={"village_intact": False},
            )
        ],
    )
    assert state.fronts["test_arc"].flags["village_intact"] is False
    # layer3 ignored
    engine.apply_impacts(
        state,
        [
            FrontImpact(
                front_id="test_arc",
                intent_id="ainz_foothold",
                effect="block",
                evidence="nope",
            )
        ],
    )
    assert state.fronts["test_arc"].status in {"active", "diverted"}


def test_variant_divert_skips_raid(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    state.minutes = 480 + 120
    engine.tick(state, 0)  # b
    state.fronts["test_arc"].flags["raid_averted"] = True
    state.minutes = 480 + 240
    engine.tick(state, 0)  # skip c via divert
    assert state.fronts["test_arc"].status == "diverted"
    assert state.fronts["test_arc"].flags.get("raid_done") is not True
    wiki_body = (tmp_path / "wiki" / "locations" / "village.md").read_text(encoding="utf-8")
    assert "Raid begins." not in wiki_body


def test_build_canon_timeline_statuses(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    timeline = engine.build_canon_timeline(state)
    assert len(timeline.fronts) == 1
    beats = {b.id: b.status for b in timeline.fronts[0].beats}
    assert beats["beat_a"] == "current"
    assert beats["beat_b"] == "upcoming"
    assert beats["beat_c"] == "upcoming"
    assert timeline.fronts[0].beats[0].due_time == "Giorno 1"

    state.minutes = 480 + 120
    engine.tick(state, 0)
    state.fronts["test_arc"].flags["raid_averted"] = True
    state.minutes = 480 + 240
    engine.tick(state, 0)
    beats = {b.id: b.status for b in engine.build_canon_timeline(state).fronts[0].beats}
    assert beats["beat_a"] == "done"
    assert beats["beat_b"] == "current"
    assert beats["beat_c"] == "skipped"


def test_timeline_marks_due_cursor_current_when_deferred(tmp_path: Path) -> None:
    """If next beat is due but deferred (player present), show it as current."""
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="village"))
    engine.activate(state, "test_arc")
    state.minutes = 480 + 120  # beat_b due; deferred because player at village
    fired = engine.sync_to_clock(state, for_display=True)
    assert fired == []
    runtime = state.fronts["test_arc"]
    assert runtime.last_fired_beat == "beat_a"
    assert runtime.cursor_beat == "beat_b"
    beats = {b.id: b.status for b in engine.build_canon_timeline(state).fronts[0].beats}
    assert beats["beat_a"] == "done"
    assert beats["beat_b"] == "current"
    assert beats["beat_c"] == "upcoming"


def test_absolute_due_ignores_late_last_fired_stamp(tmp_path: Path) -> None:
    """Beat B fires at absolute due even if last_fired_at was stamped late."""
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    runtime = state.fronts["test_arc"]
    # Pretend plea/start fired late on the wall clock
    runtime.last_fired_at_day = 1
    runtime.last_fired_at_minutes = 480 + 200
    runtime.accumulated_minutes = 0
    state.minutes = 480 + 120  # absolute due for beat_b
    fired = engine.tick(state, 0)
    assert fired == ["beat_b"]
    assert runtime.last_fired_at_minutes == 600  # due of beat_b, not wall clock


def test_defer_presence_on_display_sync(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="village"))
    engine.activate(state, "test_arc")
    state.minutes = 480 + 120
    fired = engine.sync_to_clock(state, for_display=True)
    assert fired == []
    assert state.fronts["test_arc"].cursor_beat == "beat_b"
    fired = engine.tick(state, 0)
    assert fired == ["beat_b"]


def test_tick_catches_up_when_clock_desynced(tmp_path: Path) -> None:
    """If game clock jumps ahead, absolute dues still fire."""
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="e-rantel"))
    engine.activate(state, "test_arc")
    runtime = state.fronts["test_arc"]
    state.day = 1
    state.minutes = 480 + 150
    runtime.accumulated_minutes = 30
    fired = engine.sync_to_clock(state)
    assert fired == ["beat_b"]
    assert runtime.last_fired_beat == "beat_b"
    assert runtime.cursor_beat == "beat_c"


def test_minutes_to_next_hydratable_beat_when_present(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="s1", player=PlayerState(location="village"))
    engine.activate(state, "test_arc")
    wait = engine.minutes_to_next_hydratable_beat(state)
    assert wait == 2 * 60


def test_load_real_carne_arc() -> None:
    loader = FrontLoader()
    definition = loader.load("carne_arc")
    assert definition.id == "carne_arc"
    assert definition.beats[0].id == "carne_quiet_life"
    assert "carne_intact" in definition.flags_initial
    raid = definition.beat_by_id["carne_raid_begins"]
    # G1 08:00 + 84h (24+24+12+12+12) = G4 20:00 → abs = 4*1440 + 1200
    assert raid.due_abs_minutes == 4 * 1440 + 20 * 60
