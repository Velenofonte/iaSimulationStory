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
            "cast_acting": ["hero"],
            "ambient": ["contadino", "cane"],
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
    # PG absent → no cast/situations hydrate, but place runtime is stamped
    assert state.situations == []
    assert "hero" not in state.characters_active
    loc = state.locations.get("village")
    assert loc is not None
    assert loc.atmosphere
    assert loc.events
    wiki_body = (tmp_path / "wiki" / "locations" / "village.md").read_text(encoding="utf-8")
    assert "Quiet day at village." in wiki_body


def test_ensure_scene_hydrates_on_arrival(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(
        session_id="s1",
        player=PlayerState(name="P", location="e-rantel"),
    )
    engine.activate(state, "test_arc")
    assert "hero" not in state.characters_active
    assert "hero" in state.characters_offscreen
    state.player.location = "village"
    outcome = engine.ensure_scene_at_player(state)
    # ensure never promotes to acting_cast
    assert "hero" not in state.characters_active
    assert "hero" in state.characters_offscreen
    assert state.locations["village"].atmosphere
    assert outcome.characters_nearby.get("hero") == "village" or "hero" in state.characters_offscreen


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
    # cast_in_world → nearby even when PG absent (not acting)
    assert "hero" not in state.characters_active
    assert "hero" in state.characters_offscreen

    state2 = GameState(session_id="s2", player=PlayerState(location="village"))
    engine.activate(state2, "test_arc")
    assert any("tranquillo" in s.summary for s in state2.situations)
    # cast_acting on beat_a → present when PG on-site
    assert "hero" in state2.characters_active
    loc = state2.locations.get("village")
    assert loc is not None
    assert "contadino" in (loc.ambient or [])


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
    assert "NARRATOR_ONLY" in slice_text
    assert "locale" in slice_text or "hero" in slice_text
    assert "Non ancora in gioco" in slice_text
    assert "FATTI del prossimo beat" in slice_text or "distant_cast" in slice_text
    assert "anticipare cast non ancora in gioco" not in slice_text
    # Spontaneous cast wiki pages only once the PC knows them.
    cast_ids = engine.relevant_cast_wiki_ids(state)
    assert "hero" not in cast_ids
    assert "later_npc" not in cast_ids
    # After the PC learns the name, the wiki id is allowed.
    from app.services.player_lens import learn

    learn(state, "hero", "named")
    assert "hero" in engine.relevant_cast_wiki_ids(state)


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
    outcome = engine.resolve_tick(state, 0)
    assert "beat_b" in outcome.live_beats
    assert outcome.fired_beats == []
    from app.turn.state_reducer import apply_front_outcome

    apply_front_outcome(state, outcome)
    commit = engine.commit_live_beat(state, path="canon")
    assert commit.fired_beats == ["beat_b"]


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


DISTANT_FRONT = {
    "id": "distant_arc",
    "name": "Distant Arc",
    "start": {"day": 1, "minutes": 480, "beat": "beat_a"},
    "flags_initial": {"a_done": False},
    "cast": {
        "kael": {
            "wiki": "kael",
            "role": "guida",
            "appear_from": "beat_a",
            "default_location": "sentiero",
        },
        "boss": {
            "wiki": "boss",
            "role": "capo dell'orda",
            "appear_from": "beat_b",
            "default_location": "sentiero",
        },
    },
    "intents_layer2": [],
    "intents_layer3": [],
    "beats": [
        {
            "id": "beat_a",
            "title": "Quiet trail",
            "place": "sentiero",
            "hours_after_previous": 0,
            "cast_in_world": ["kael"],
            "cast_acting": ["kael"],
            "scene_canon": "Il sentiero e' quieto.\n",
            "on_fire": {"marks": ["a_done"]},
        },
        {
            "id": "beat_b",
            "title": "Column arrives",
            "place": "sentiero",
            "hours_after_previous": 2,
            "prereq": {"all": ["a_done"]},
            "cast_in_world": ["boss", "kael"],
            "scene_canon": "Una colonna si ferma in fondo alla valle.\n",
            "on_fire": {"marks": ["b_done"]},
        },
    ],
    "variants": [],
}


def _distant_engine(tmp: Path) -> FrontEngine:
    fronts = tmp / "fronts"
    fronts.mkdir(parents=True)
    (fronts / "distant_arc.yaml").write_text(
        yaml.safe_dump(DISTANT_FRONT, allow_unicode=True), encoding="utf-8"
    )
    wiki = tmp / "wiki"
    (wiki / "locations").mkdir(parents=True)
    (wiki / "characters").mkdir(parents=True)
    trail = frontmatter.Post("# Sentiero\n", id="sentiero", name="Sentiero")
    (wiki / "locations" / "sentiero.md").write_text(
        frontmatter.dumps(trail), encoding="utf-8"
    )
    for cid, name, body in (
        ("kael", "Kael", "# Kael\n\n# Aspetto fisico\nUmano snello.\n"),
        ("boss", "Boss", "# Boss\n\n# Aspetto fisico\nDemone cornuti e fiamme.\n"),
    ):
        post = frontmatter.Post(body, id=cid, name=name, tier="canonical")
        (wiki / "characters" / f"{cid}.md").write_text(
            frontmatter.dumps(post), encoding="utf-8"
        )
    return FrontEngine(
        loader=FrontLoader(fronts_dir=fronts),
        wiki=WikiWriter(wiki_dir=wiki),
    )


def test_distant_cast_from_pending_beat(tmp_path: Path) -> None:
    engine = _distant_engine(tmp_path)
    state = GameState(session_id="d1", player=PlayerState(location="sentiero"))
    engine.activate(state, "distant_arc")
    # beat_a fired; cursor on beat_b → boss is distant, kael already appear_from fired
    assert state.fronts["distant_arc"].last_fired_beat == "beat_a"
    assert state.fronts["distant_arc"].cursor_beat == "beat_b"
    distant = engine.distant_cast_wiki_ids(state)
    assert distant == ["boss"]
    entries = engine.distant_cast_entries(state)
    assert entries == [{"id": "boss", "role": "capo dell'orda"}]
    # relevant_cast still requires know + fired appear_from
    assert "boss" not in engine.relevant_cast_wiki_ids(state)


def test_distant_cast_includes_subplace(tmp_path: Path) -> None:
    engine = _distant_engine(tmp_path)
    state = GameState(
        session_id="d2", player=PlayerState(location="sentiero-sud")
    )
    engine.activate(state, "distant_arc")
    assert engine.distant_cast_wiki_ids(state) == ["boss"]


def test_distant_cast_empty_on_other_place(tmp_path: Path) -> None:
    engine = _distant_engine(tmp_path)
    state = GameState(session_id="d3", player=PlayerState(location="osteria"))
    engine.activate(state, "distant_arc")
    assert engine.distant_cast_wiki_ids(state) == []
    assert engine.distant_cast_entries(state) == []


def test_distant_cast_excludes_present(tmp_path: Path) -> None:
    engine = _distant_engine(tmp_path)
    state = GameState(
        session_id="d4",
        player=PlayerState(location="sentiero"),
        characters_active=["boss"],
    )
    engine.activate(state, "distant_arc")
    assert engine.distant_cast_wiki_ids(state) == []


def test_distant_card_aspect_only_and_extra(tmp_path: Path) -> None:
    from app.narrative.narrative_context import NarrativeContextAssembler
    from app.narrative.prompt_builder import PromptBuilder
    from app.models import CharacterCard
    from app.wiki.wiki_query import WikiQuery

    engine = _distant_engine(tmp_path)
    state = GameState(session_id="d5", player=PlayerState(location="sentiero", name="Ray"))
    engine.activate(state, "distant_arc")

    # PromptBuilder distant flag
    card = CharacterCard(
        id="boss",
        name="Boss",
        tier="canonical",
        role="capo",
        body="# Aspetto fisico\nDemone cornuti.\n\n# Capacita di combattimento\nDistrugge muri.\n",
    )
    text = PromptBuilder().build_prompt_card(card, distant=True, lens_level="seen")
    assert "distant: non in present" in text
    assert "Aspetto fisico" in text
    assert "Demone cornuti" in text
    assert "Capacita" not in text and "Distrugge" not in text

    ctx = NarrativeContextAssembler(fronts=engine, wiki_writer=engine.wiki)
    ctx.wiki = WikiQuery(wiki_dir=engine.wiki.wiki_dir)
    extra = ctx.location_scene_extra(state)
    assert extra.get("distant_cast") == [{"id": "boss", "role": "capo dell'orda"}]
    cards, ids = ctx._build_character_cards(state, active_arcs=[])
    joined = "\n".join(cards)
    assert "boss" in ids
    assert "distant: non in present" in joined
    assert "Demone cornuti" in joined or "cornuti" in joined.lower()


def test_clock_caps_wait_on_subplace_and_fires(tmp_path: Path) -> None:
    """Wait past a hydratable beat on a sub-place advances only to the window then goes live."""
    from app.turn.chat_turn import advance_minutes_capped_to_front

    engine = _engine(tmp_path)
    state = GameState(
        session_id="cap1",
        player=PlayerState(location="village-south"),
        day=1,
        minutes=480,
    )
    engine.activate(state, "test_arc")
    runtime = state.fronts["test_arc"]
    assert runtime.cursor_beat == "beat_b"
    # beat_b due at 480 + 120 = 600 → set clock 8 minutes early
    state.minutes = 592
    assert engine.minutes_to_next_hydratable_beat(state) == 8

    added = advance_minutes_capped_to_front(
        state, engine, "breve", 30, player_action="aspetto", stance="wait"
    )
    assert added == 8
    assert state.minutes == 600
    outcome = engine.resolve_tick(state, added)
    assert "beat_b" in outcome.live_beats
    assert "beat_b" not in outcome.fired_beats
    assert runtime.live_beat_id == "beat_b"
    assert "beat_b_done" not in runtime.flags or runtime.flags.get("beat_b_done") is not True


def test_clock_cap_zero_enters_live_same_turn_on_observe(tmp_path: Path) -> None:
    """Already-due beat (cap=0) + scruto enters live in the same resolve_tick (no commit)."""
    from app.turn.chat_turn import advance_minutes_capped_to_front

    engine = _engine(tmp_path)
    state = GameState(
        session_id="cap0",
        player=PlayerState(location="village-sud"),
        day=1,
        minutes=480,
    )
    engine.activate(state, "test_arc")
    state.minutes = 600  # beat_b already in window
    assert engine.minutes_to_next_hydratable_beat(state) == 0

    added = advance_minutes_capped_to_front(
        state, engine, "istantanea", 5, player_action="scruto il villaggio", stance="passive"
    )
    assert added == 0
    outcome = engine.resolve_tick(state, added)
    assert "beat_b" in outcome.live_beats
    assert outcome.fired_beats == []
    # While live, clock is not capped to the beat window
    assert engine.minutes_to_next_hydratable_beat(state) is None


def test_front_due_now_payload_and_extra(tmp_path: Path) -> None:
    from app.narrative.narrative_context import NarrativeContextAssembler
    from app.wiki.wiki_query import WikiQuery

    engine = _engine(tmp_path)
    state = GameState(
        session_id="due1",
        player=PlayerState(location="village-south", name="Ray"),
        day=1,
        minutes=480,
    )
    engine.activate(state, "test_arc")
    state.minutes = 600
    payload = engine.front_due_now_payload(state)
    assert payload is not None
    assert payload["id"] == "beat_b"
    assert payload["place"] == "village"
    assert payload["bullets"]
    assert any("voci" in b.lower() or "armati" in b.lower() for b in payload["bullets"])

    ctx = NarrativeContextAssembler(fronts=engine, wiki_writer=engine.wiki)
    ctx.wiki = WikiQuery(wiki_dir=engine.wiki.wiki_dir)
    extra = ctx.location_scene_extra(state)
    assert extra.get("front_due_now", {}).get("id") == "beat_b"
    assert extra.get("front_live", {}).get("id") == "beat_b"
    assert extra.get("front_live", {}).get("status") == "due"

    # Not due yet → no payload
    state.minutes = 500
    assert engine.front_due_now_payload(state) is None
    assert "front_due_now" not in ctx.location_scene_extra(state)


def test_live_still_live_keeps_cursor(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(
        session_id="live1",
        player=PlayerState(location="village-south"),
        day=1,
        minutes=600,
    )
    engine.activate(state, "test_arc")
    state.minutes = 600
    engine.resolve_tick(state, 0)
    runtime = state.fronts["test_arc"]
    assert runtime.live_beat_id == "beat_b"
    assert runtime.cursor_beat == "beat_b"
    # Second tick while still on site: stay live
    out2 = engine.resolve_tick(state, 0)
    assert out2.fired_beats == []
    assert runtime.live_beat_id == "beat_b"
    assert runtime.cursor_beat == "beat_b"
    # Explicit still_live commit is a no-op
    out3 = engine.commit_live_beat(state, path="still_live", note="talking to actor")
    assert out3.fired_beats == []
    assert runtime.live_beat_id == "beat_b"
    assert runtime.cursor_beat == "beat_b"
    assert runtime.flags.get("beat_b_done") is not True


def _live_state(tmp_path: Path, session: str) -> tuple[FrontEngine, GameState]:
    engine = _engine(tmp_path)
    state = GameState(
        session_id=session,
        player=PlayerState(location="village-south"),
        day=1,
        minutes=600,
    )
    engine.activate(state, "test_arc")
    state.minutes = 600
    engine.resolve_tick(state, 0)
    assert state.fronts["test_arc"].live_beat_id == "beat_b"
    return engine, state


def test_live_clock_alone_never_commits(tmp_path: Path) -> None:
    """No timer: repeated ticks keep the window open until the turn decides."""
    engine, state = _live_state(tmp_path, "hold0")
    runtime = state.fronts["test_arc"]
    for _ in range(6):
        outcome = engine.resolve_tick(state, 0)
        assert outcome.fired_beats == []
    assert runtime.live_beat_id == "beat_b"
    assert runtime.cursor_beat == "beat_b"


def test_live_hold_needs_new_fact(tmp_path: Path) -> None:
    """A new fact renews the wait; engagement alone also holds without allow_land."""
    engine, state = _live_state(tmp_path, "hold1")
    runtime = state.fronts["test_arc"]

    path = engine.live_commit_path(
        state,
        proposed="still_live",
        progress_key="sit:soldiers_called",
        hold_reason="il capo sta rispondendo al PG",
        engagement=True,
    )
    assert path == "still_live"
    assert runtime.live_progress_key == "sit:soldiers_called"
    assert runtime.live_hold_reason == "il capo sta rispondendo al PG"

    # Same fact signature next turn, but PC still engaged → hold
    assert (
        engine.live_commit_path(
            state,
            proposed="still_live",
            progress_key="sit:soldiers_called",
            engagement=True,
        )
        == "still_live"
    )
    # No engagement and no allow_land → still hold (no blind echo→canon)
    assert (
        engine.live_commit_path(
            state,
            proposed="still_live",
            progress_key="sit:soldiers_called",
            engagement=False,
            allow_land=False,
        )
        == "still_live"
    )
    # Wait / allow_land with nothing left to play → actor resolves
    assert (
        engine.live_commit_path(
            state,
            proposed="still_live",
            progress_key="sit:soldiers_called",
            engagement=False,
            allow_land=True,
        )
        == "canon"
    )


def test_live_echo_turn_commits_canon(tmp_path: Path) -> None:
    engine, state = _live_state(tmp_path, "hold2")
    # Empty progress alone does not force canon
    assert (
        engine.live_commit_path(state, proposed="still_live", progress_key="")
        == "still_live"
    )
    assert (
        engine.live_commit_path(
            state, proposed="still_live", progress_key="", allow_land=True
        )
        == "canon"
    )


def test_live_interference_forces_alt(tmp_path: Path) -> None:
    engine, state = _live_state(tmp_path, "hold3")
    engine.apply_impacts(
        state,
        [
            FrontImpact(
                front_id="test_arc",
                intent_id="pressure_village",
                effect="distort",
                evidence="il PG ostacola il mezzo di default",
            )
        ],
    )
    assert state.fronts["test_arc"].live_interference is True
    # allow_land after interference: the means bends instead of playing out
    assert (
        engine.live_commit_path(
            state, proposed="still_live", progress_key="", allow_land=True
        )
        == "alt"
    )
    # Even an explicit canon proposal is redirected to alt
    assert engine.live_commit_path(state, proposed="canon", progress_key="") == "alt"


def test_live_commit_path_none_without_live_window(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    state = GameState(session_id="hold4", player=PlayerState(location="village"))
    engine.activate(state, "test_arc")
    assert engine.live_commit_path(state, proposed="still_live", progress_key="x") is None


def test_front_live_payload_reports_hold_reason(tmp_path: Path) -> None:
    engine, state = _live_state(tmp_path, "hold5")
    payload = engine.front_live_payload(state)
    assert payload is not None
    assert payload["status"] == "live"
    assert payload["hold_reason"] is None
    assert payload["hold_needs_new_fact"] is True

    engine.live_commit_path(
        state,
        proposed="still_live",
        progress_key="find:tracce",
        hold_reason="il PG sta studiando il mezzo",
    )
    payload = engine.front_live_payload(state)
    assert payload is not None
    assert payload["hold_reason"] == "il PG sta studiando il mezzo"


def test_live_progress_key_ignores_derived_threads() -> None:
    from app.models.game_state import NpcKnowledgeFact
    from app.models.narrative import NarrativeTime
    from app.models.turn import TurnResolution
    from app.turn.turn_pipeline import TurnPipeline

    def resolution(**kwargs: object) -> TurnResolution:
        return TurnResolution(time=NarrativeTime(bucket="istantanea", minutes=3), **kwargs)

    # Engine-derived threads (brief_/episode_/front_) are not player facts
    derived = resolution(
        situations_add=[
            NpcKnowledgeFact(id="brief_il_pg_guarda", summary="brief"),
            NpcKnowledgeFact(id="front_beat_b_0_x", summary="hydrate"),
            NpcKnowledgeFact(id="episode_arrivo_village", summary="episodio"),
        ]
    )
    assert (
        TurnPipeline._live_progress_key(derived, previous_situation_ids=set()) == ""
    )

    real = resolution(
        situations_add=[NpcKnowledgeFact(id="patto_col_capo", summary="accordo")]
    )
    assert (
        TurnPipeline._live_progress_key(real, previous_situation_ids=set())
        == "sit:patto_col_capo"
    )
    # Already-open thread is not new either
    assert (
        TurnPipeline._live_progress_key(
            real, previous_situation_ids={"patto_col_capo"}
        )
        == ""
    )

    joined = resolution(present_join=["sergente"])
    assert "join:sergente" in TurnPipeline._live_progress_key(
        joined, previous_situation_ids=set()
    )


def test_live_commit_canon_advances(tmp_path: Path) -> None:
    from app.turn.state_reducer import apply_front_outcome

    engine = _engine(tmp_path)
    state = GameState(
        session_id="live2",
        player=PlayerState(location="village"),
        day=1,
        minutes=600,
    )
    engine.activate(state, "test_arc")
    state.minutes = 600
    apply_front_outcome(state, engine.resolve_tick(state, 0))
    runtime = state.fronts["test_arc"]
    assert runtime.live_beat_id == "beat_b"
    outcome = engine.commit_live_beat(state, path="canon")
    apply_front_outcome(state, outcome)
    assert "beat_b" in outcome.fired_beats
    assert runtime.live_beat_id is None
    assert runtime.last_fired_beat == "beat_b"
    assert runtime.cursor_beat == "beat_c"
    assert runtime.flags.get("beat_b_done") is True


def test_live_commit_alt_diverts_without_closing_events(tmp_path: Path) -> None:
    from app.turn.state_reducer import apply_front_outcome

    engine = _engine(tmp_path)
    state = GameState(
        session_id="live3",
        player=PlayerState(location="village"),
        day=1,
        minutes=600,
    )
    engine.activate(state, "test_arc")
    state.minutes = 600
    apply_front_outcome(state, engine.resolve_tick(state, 0))
    outcome = engine.commit_live_beat(
        state, path="alt", note="default means blocked; pressure continues"
    )
    apply_front_outcome(state, outcome)
    runtime = state.fronts["test_arc"]
    assert runtime.status == "diverted"
    assert runtime.live_beat_id is None
    assert runtime.cursor_beat == "beat_c"
    assert any("alt path" in n or "blocked" in n for n in runtime.distortion_notes)
    # Layer 3 pressure stays on; next beat still to satisfy
    definition = engine.loader.load("test_arc")
    assert definition.intents_layer3
    assert runtime.status != "resolved"
    # Alt does not stamp closing location_events from scene_canon
    assert outcome.location_events == {}


def test_live_leave_place_commits_off_camera(tmp_path: Path) -> None:
    from app.turn.state_reducer import apply_front_outcome

    engine = _engine(tmp_path)
    state = GameState(
        session_id="live4",
        player=PlayerState(location="village"),
        day=1,
        minutes=600,
    )
    engine.activate(state, "test_arc")
    state.minutes = 600
    apply_front_outcome(state, engine.resolve_tick(state, 0))
    assert state.fronts["test_arc"].live_beat_id == "beat_b"
    state.player.location = "e-rantel"
    outcome = engine.commit_live_beat(
        state, path="canon", note="left place while live", hydrate_scene=False
    )
    apply_front_outcome(state, outcome)
    runtime = state.fronts["test_arc"]
    assert runtime.live_beat_id is None
    assert runtime.last_fired_beat == "beat_b"
    assert "beat_b" in outcome.fired_beats


def test_timeline_marks_live_beat(tmp_path: Path) -> None:
    from app.turn.state_reducer import apply_front_outcome

    engine = _engine(tmp_path)
    state = GameState(session_id="tl1", player=PlayerState(location="village"))
    engine.activate(state, "test_arc")
    state.minutes = 600
    apply_front_outcome(state, engine.resolve_tick(state, 0))
    beats = {b.id: b.status for b in engine.build_canon_timeline(state).fronts[0].beats}
    assert beats["beat_a"] == "done"
    assert beats["beat_b"] == "live"
    assert beats["beat_c"] == "upcoming"


# --- Fictional fronts (pillar / means-inflight); zero setting lore ---

PILLAR_FRONT = {
    "id": "gate_arc",
    "name": "Gate Arc",
    "start": {"day": 1, "minutes": 480, "beat": "watch"},
    "flags_initial": {"gate_intact": True},
    "cast": {
        "warden": {
            "wiki": "warden",
            "role": "guard",
            "appear_from": "watch",
            "default_location": "gate",
        }
    },
    "intents_layer3": [{"id": "siege_pressure", "summary": "siege continues"}],
    "beats": [
        {
            "id": "watch",
            "title": "Quiet watch",
            "place": "gate",
            "hours_after_previous": 0,
            "prereq": {"all": ["gate_intact"]},
            "cast_in_world": ["warden"],
            "scene_canon": "The gate is quiet.\n",
            "on_fire": {"marks": ["watch_done"]},
        },
        {
            "id": "gate_break",
            "title": "Gate break",
            "place": "gate",
            "hours_after_previous": 2,
            "pillar": True,
            "prereq": {"all": ["watch_done", "gate_intact"]},
            "cast_in_world": ["warden"],
            "scene_canon": "A siege engine smashes the gate.\nThe wall collapses.\n",
            "on_fire": {
                "wiki_writes": [
                    {"entity": "gate", "events_add": ["Gate smashed open."]}
                ],
                "marks": ["gate_broken", "gate_break_done"],
            },
        },
        {
            "id": "aftermath_talk",
            "title": "Aftermath talk",
            "place": "gate",
            "hours_after_previous": 2,
            "pillar": False,
            "prereq": {"all": ["gate_break_done"]},
            "scene_canon": "Survivors argue about the next stand.\n",
            "on_fire": {"marks": ["aftermath_done"]},
        },
    ],
}


def _pillar_engine(tmp: Path) -> FrontEngine:
    fronts = tmp / "fronts"
    fronts.mkdir(parents=True)
    (fronts / "gate_arc.yaml").write_text(
        yaml.safe_dump(PILLAR_FRONT, allow_unicode=True), encoding="utf-8"
    )
    wiki = tmp / "wiki"
    (wiki / "locations").mkdir(parents=True)
    (wiki / "characters").mkdir(parents=True)
    gate = frontmatter.Post("# Gate\n\n# Eventi\n\n", id="gate", name="Gate")
    (wiki / "locations" / "gate.md").write_text(
        frontmatter.dumps(gate), encoding="utf-8"
    )
    post = frontmatter.Post("# Warden\n", id="warden", name="Warden", tier="minimal")
    (wiki / "characters" / "warden.md").write_text(
        frontmatter.dumps(post), encoding="utf-8"
    )
    return FrontEngine(
        loader=FrontLoader(fronts_dir=fronts),
        wiki=WikiWriter(wiki_dir=wiki),
    )


def _pillar_live(tmp: Path, session: str) -> tuple[FrontEngine, GameState]:
    from app.turn.state_reducer import apply_front_outcome

    engine = _pillar_engine(tmp)
    state = GameState(
        session_id=session,
        player=PlayerState(location="gate"),
        day=1,
        minutes=600,
    )
    engine.activate(state, "gate_arc")
    state.minutes = 600
    apply_front_outcome(state, engine.resolve_tick(state, 0))
    assert state.fronts["gate_arc"].live_beat_id == "gate_break"
    return engine, state


def test_loader_reads_pillar_flag(tmp_path: Path) -> None:
    engine = _pillar_engine(tmp_path)
    definition = engine.loader.load("gate_arc")
    assert definition.beat_by_id["gate_break"].pillar is True
    assert definition.beat_by_id["aftermath_talk"].pillar is False


def test_means_inflight_blocks_canon_until_land(tmp_path: Path) -> None:
    engine, state = _pillar_live(tmp_path, "inflight1")
    runtime = state.fronts["gate_arc"]
    path = engine.live_commit_path(
        state,
        proposed="canon",
        progress_key="",
        means_inflight=True,
        allow_land=False,
    )
    assert path == "still_live"
    assert runtime.live_means_inflight is True
    assert runtime.live_beat_id == "gate_break"

    path2 = engine.live_commit_path(
        state,
        proposed="canon",
        progress_key="",
        means_inflight=False,
        allow_land=True,
    )
    assert path2 == "canon"


def test_engagement_holds_without_progress_key(tmp_path: Path) -> None:
    engine, state = _pillar_live(tmp_path, "engage1")
    assert (
        engine.live_commit_path(
            state,
            proposed="still_live",
            progress_key="",
            engagement=True,
        )
        == "still_live"
    )


def test_pillar_failed_interrupts_without_advancing(tmp_path: Path) -> None:
    from app.turn.state_reducer import apply_front_outcome

    engine, state = _pillar_live(tmp_path, "pillar_fail")
    runtime = state.fronts["gate_arc"]
    cursor_before = runtime.cursor_beat
    outcome = engine.commit_live_beat(
        state, path="pillar_failed", note="gate held; step missing"
    )
    apply_front_outcome(state, outcome)
    assert runtime.status == "interrupted"
    assert runtime.live_beat_id is None
    assert runtime.cursor_beat == cursor_before
    assert runtime.flags.get("gate_break_done") is not True
    assert outcome.location_events == {}
    assert outcome.fired_beats == []


def test_pillar_alt_other_means_advances_queue(tmp_path: Path) -> None:
    from app.turn.state_reducer import apply_front_outcome

    engine, state = _pillar_live(tmp_path, "pillar_alt")
    runtime = state.fronts["gate_arc"]
    outcome = engine.commit_live_beat(
        state, path="alt", note="sappers opened a side breach"
    )
    apply_front_outcome(state, outcome)
    assert runtime.status == "diverted"
    assert runtime.cursor_beat == "aftermath_talk"
    assert runtime.flags.get("gate_break_done") is True
    assert outcome.location_events == {}


def test_non_pillar_skip_advances_queue(tmp_path: Path) -> None:
    from app.turn.state_reducer import apply_front_outcome

    engine, state = _pillar_live(tmp_path, "skip1")
    # Complete pillar first via canon so cursor reaches non-pillar beat
    apply_front_outcome(state, engine.commit_live_beat(state, path="canon"))
    runtime = state.fronts["gate_arc"]
    assert runtime.cursor_beat == "aftermath_talk"
    state.minutes = 720
    apply_front_outcome(state, engine.resolve_tick(state, 0))
    assert runtime.live_beat_id == "aftermath_talk"
    assert engine.loader.load("gate_arc").beat_by_id["aftermath_talk"].pillar is False

    path = engine.live_commit_path(state, proposed="skip", progress_key="")
    assert path == "skip"
    outcome = engine.commit_live_beat(
        state, path="skip", note="talk skipped; pressure continues"
    )
    apply_front_outcome(state, outcome)
    assert runtime.live_beat_id is None
    assert runtime.last_fired_beat == "aftermath_talk"
    assert runtime.flags.get("aftermath_done") is True


def test_skip_on_pillar_becomes_pillar_failed(tmp_path: Path) -> None:
    engine, state = _pillar_live(tmp_path, "skip_pillar")
    assert (
        engine.live_commit_path(state, proposed="skip", progress_key="")
        == "pillar_failed"
    )


def test_front_live_payload_exposes_pillar_and_inflight(tmp_path: Path) -> None:
    engine, state = _pillar_live(tmp_path, "payload1")
    engine.live_commit_path(
        state,
        proposed="still_live",
        progress_key="",
        means_inflight=True,
        engagement=True,
    )
    payload = engine.front_live_payload(state)
    assert payload is not None
    assert payload["pillar"] is True
    assert payload["means_inflight"] is True


def test_arc_timeline_includes_pillar_flag(tmp_path: Path) -> None:
    engine, state = _pillar_live(tmp_path, "tl_pillar")
    beats = {b.id: b for b in engine.build_canon_timeline(state).fronts[0].beats}
    assert beats["gate_break"].pillar is True
    assert beats["aftermath_talk"].pillar is False
    assert beats["gate_break"].status == "live"
