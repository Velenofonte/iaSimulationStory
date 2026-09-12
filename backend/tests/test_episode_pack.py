"""Tests for episode pack loading (agnostic defaults + story overlay)."""

from pathlib import Path

from app.services.episode_pack import (
    EpisodePackLoader,
    default_episode_pack,
    parse_episode_pack,
)


def test_default_pack_has_seven_tiers() -> None:
    pack = default_episode_pack()
    assert set(pack.tiers.keys()) == {0, 1, 2, 3, 4, 5, 6}
    assert pack.tier_label(0) == "niente"
    assert "default" in pack.location_kinds
    assert len(pack.location_profile("outpost")) == 7
    # T1 slot is reserved but never weighted in defaults.
    assert pack.location_profile("outpost")[1] == 0
    assert 1 not in pack.kinds["discovery"]["tiers"]
    assert "threat" in pack.kinds
    assert pack.scale_weight("A++") > pack.scale_weight("F")
    assert pack.modifier("baseline_calm")[0] > 1.0
    assert pack.modifier("baseline_calm")[1] == 0.0


def test_parse_overlay_replaces_location_profile() -> None:
    pack = parse_episode_pack(
        {
            "location_kinds": {"outpost": [90, 5, 2, 1, 1, 0.5, 0.5]},
            "tiers": {5: "pericolo"},
        }
    )
    assert pack.location_profile("outpost")[0] == 90
    assert pack.tier_label(5) == "pericolo"
    # Unmentioned kinds keep defaults.
    assert "social" in pack.kinds


def test_loader_uses_story_file(tmp_path: Path, monkeypatch) -> None:
    stories = tmp_path / "stories" / "demo"
    stories.mkdir(parents=True)
    (stories / "events.yaml").write_text(
        "tiers:\n  0: none\nlocation_kinds:\n  default: [100, 0, 0, 0, 0, 0, 0]\n",
        encoding="utf-8",
    )
    from app.config import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    loader = EpisodePackLoader()
    pack = loader.load("demo", force=True)
    assert pack.tier_label(0) == "none"
    assert pack.location_profile("default")[0] == 100


def test_loader_missing_file_falls_back_to_defaults(tmp_path: Path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    loader = EpisodePackLoader()
    pack = loader.load("missing-story", force=True)
    assert pack.tier_label(2) == "gancio"
