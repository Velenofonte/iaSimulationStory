"""Distant cast joins present when the PC engages them."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import yaml

from app.models import GameState, PlayerState
from app.models.narrative import NarrativeTime
from app.models.turn import TurnResolution
from app.story.front_engine import FrontEngine
from app.story.front_loader import FrontLoader
from app.turn.turn_pipeline import TurnPipeline
from app.wiki.wiki_query import WikiQuery
from app.wiki.wiki_writer import WikiWriter


DISTANT_FRONT = {
    "id": "distant_arc",
    "name": "Distant",
    "start": {"day": 1, "minutes": 480, "beat": "beat_a"},
    "flags_initial": {},
    "cast": {
        "boss": {
            "wiki": "boss",
            "role": "capo dell'orda",
            "appear_from": "beat_b",
            "default_location": "sentiero",
        }
    },
    "beats": [
        {
            "id": "beat_a",
            "title": "Approach",
            "place": "sentiero",
            "hours_after_previous": 0,
            "cast_in_world": [],
            "scene_canon": "Quiet road.\n",
            "on_fire": {"marks": ["beat_a_done"]},
        },
        {
            "id": "beat_b",
            "title": "Face",
            "place": "sentiero",
            "hours_after_previous": 1,
            "prereq": {"all": ["beat_a_done"]},
            "cast_in_world": ["boss"],
            "scene_canon": "The boss looms.\n",
            "on_fire": {"marks": ["beat_b_done"]},
            "if_player_present": "narrate_symptoms_or_edge",
        },
    ],
}


def _setup(tmp: Path) -> tuple[TurnPipeline, FrontEngine, GameState]:
    fronts = tmp / "fronts"
    fronts.mkdir(parents=True)
    (fronts / "distant_arc.yaml").write_text(
        yaml.safe_dump(DISTANT_FRONT, allow_unicode=True), encoding="utf-8"
    )
    wiki = tmp / "wiki"
    (wiki / "locations").mkdir(parents=True)
    (wiki / "characters").mkdir(parents=True)
    loc = frontmatter.Post("# Road\n", id="sentiero", name="Sentiero")
    (wiki / "locations" / "sentiero.md").write_text(
        frontmatter.dumps(loc), encoding="utf-8"
    )
    boss = frontmatter.Post(
        "# Boss\n\n# Aspetto fisico\nTall.\n",
        id="boss",
        name="Boss",
        tier="minimal",
    )
    (wiki / "characters" / "boss.md").write_text(
        frontmatter.dumps(boss), encoding="utf-8"
    )
    engine = FrontEngine(
        loader=FrontLoader(fronts_dir=fronts),
        wiki=WikiWriter(wiki_dir=wiki),
    )
    query = WikiQuery(wiki_dir=wiki)
    pipe = TurnPipeline.__new__(TurnPipeline)
    pipe.fronts = engine
    pipe.query = query
    state = GameState(
        session_id="join1",
        player=PlayerState(location="sentiero"),
        day=1,
        minutes=540,
    )
    engine.activate(state, "distant_arc")
    assert engine.distant_cast_wiki_ids(state) == ["boss"]
    return pipe, engine, state


def test_engage_by_name_joins_distant(tmp_path: Path) -> None:
    pipe, _engine, state = _setup(tmp_path)
    resolution = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        scene_brief=["Il boss resta in silenzio"],
        present_join=[],
    )
    out = pipe._ensure_distant_engagement_joins(
        resolution,
        message='Alzo la voce: "Ehi Boss, ti parlo"',
        state=state,
        state_present=[],
    )
    assert "boss" in (out.present_join or [])


def test_engage_via_brief_joins_distant(tmp_path: Path) -> None:
    pipe, _engine, state = _setup(tmp_path)
    resolution = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        scene_brief=["Boss — risponde al PG — voce bassa"],
        present_join=[],
    )
    out = pipe._ensure_distant_engagement_joins(
        resolution,
        message="aspetto",
        state=state,
        state_present=[],
    )
    assert "boss" in (out.present_join or [])


def test_observe_only_does_not_join(tmp_path: Path) -> None:
    pipe, _engine, state = _setup(tmp_path)
    resolution = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        scene_brief=["Una figura enorme e' visibile in lontananza"],
        present_join=[],
    )
    out = pipe._ensure_distant_engagement_joins(
        resolution,
        message="scruto la figura in lontananza",
        state=state,
        state_present=[],
    )
    assert out.present_join == [] or out.present_join is None or list(out.present_join) == []
