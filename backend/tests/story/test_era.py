"""Tests for era loader, seed, reach filter, overlays."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from app.models import GameState, PlayerState
from app.models.game_state import ChronicleEntry
from app.services.era_loader import EraLoader, parse_era_dict
from app.services.front_engine import FrontEngine
from app.services.front_loader import FrontLoader
from app.services.story_engine import (
    StoryEngine,
    epoch_overlay_ids,
    filter_chronicle_for_player,
    player_is_insider,
)
from app.services.wiki_overlay import merge_character_with_overlays
from app.services.wiki_writer import WikiWriter


def test_parse_holy_kingdom_era():
    loader = EraLoader(story_id="overlord")
    era = loader.load("holy_kingdom")
    assert era.id == "holy_kingdom"
    assert era.entry_arc == "hk_invasion"
    assert "hk_embassy" in era.arc_by_id
    assert era.world_flags.get("sorcerer_kingdom_founded") is True
    assert any(c.secret for c in era.chronicle)
    assert era.start_location == "hoburns"


def test_era_rejects_secret_with_public_reach():
    with pytest.raises(ValueError, match="secret"):
        parse_era_dict(
            {
                "id": "bad",
                "start": {"location": "x"},
                "chronicle": [
                    {
                        "id": "leak",
                        "summary": "secret",
                        "reach": "world",
                        "secret": True,
                    }
                ],
            }
        )


def test_seed_era_writes_chronicle(tmp_path: Path):
    wiki = WikiWriter(wiki_dir=tmp_path)
    # Minimal fronts dir so activate can fail soft — use real seed fronts
    from app.config import settings

    fronts = FrontEngine(
        loader=FrontLoader(fronts_dir=settings.fronts_dir),
        wiki=wiki,
    )
    story = StoryEngine(
        fronts=fronts,
        wiki=wiki,
        era_loader=EraLoader(story_id="overlord"),
        front_loader=fronts.loader,
    )
    fronts.story = story
    state = GameState(
        session_id="t",
        story_id="overlord",
        player=PlayerState(name="Rayan", location="e-rantel"),
    )
    era = story.seed_era(state, "holy_kingdom", activate_entry=True, fire_start=False)
    assert state.story.era == "holy_kingdom"
    assert state.player.location == "hoburns"
    assert state.story.chronicle
    assert all(c.source == "canon_digest" for c in state.story.chronicle)
    assert (tmp_path / "world" / "cronaca.md").exists()
    post = frontmatter.load(tmp_path / "world" / "cronaca.md")
    assert "Cronaca" in post.content
    assert "Cronaca occulta" in post.content
    assert state.story.current_arc == era.entry_arc
    assert "hk_invasion" in state.fronts


def test_reach_filter_hides_secrets_from_external():
    entries = [
        ChronicleEntry(id="a", summary="pubblico", reach="world"),
        ChronicleEntry(id="b", summary="segreto", reach="none", secret=True),
    ]
    visible = filter_chronicle_for_player(entries, is_insider=False)
    assert [e.id for e in visible] == ["a"]
    insider = filter_chronicle_for_player(entries, is_insider=True)
    assert {e.id for e in insider} == {"a", "b"}


def test_epoch_overlay_ids_includes_era():
    state = GameState(
        session_id="t",
        player=PlayerState(name="X", location="hoburns"),
    )
    state.story.era = "holy_kingdom"
    assert epoch_overlay_ids(state) == ["holy_kingdom"]


def test_holy_kingdom_overlay_applies_without_active_front():
    from app.config import settings

    wiki = settings.wiki_dir
    ainz = wiki / "characters" / "ainz.md"
    if not ainz.exists():
        pytest.skip("ainz sheet missing")
    post = frontmatter.load(ainz)
    meta, body = merge_character_with_overlays(
        base_meta=dict(post.metadata),
        base_body=post.content,
        wiki_dir=wiki,
        entity_stem="ainz",
        active_arc_ids=["holy_kingdom"],
    )
    assert "holy_kingdom" in str(meta.get("arc_overlay") or meta.get("arc") or "")
    # Overlay should mention Sorcerer King / Re Stregone era titles
    assert "Stregone" in body or "Sorcerer" in body or "Re Stregone" in body


def test_player_is_insider():
    loader = EraLoader(story_id="overlord")
    era = loader.load("holy_kingdom")
    state = GameState(
        session_id="t",
        player=PlayerState(name="Ainz", location="x", character_id="ainz"),
    )
    assert player_is_insider(state, era) is True
    state.player.character_id = "rayan"
    assert player_is_insider(state, era) is False
