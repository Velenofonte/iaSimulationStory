"""Tests for per-spell epistemic tags."""

from pathlib import Path

from app.wiki.spell_tags import (
    format_spell_line,
    infer_spell_tags,
    parse_spell_entry_line,
)
from app.wiki.wiki_writer import WikiWriter


def test_infer_detect_power_info() -> None:
    out, man = infer_spell_tags(
        "Detect Power",
        "Magia capace di rilevare, identificare e localizzare forme di vita",
    )
    assert out == "info"
    assert man == "visible"


def test_infer_italian_rileva() -> None:
    out, _ = infer_spell_tags("Alert", "magia di tier 2 che rileva e avvisa di possibili minacce")
    assert out == "info"


def test_infer_fly_effect() -> None:
    out, man = infer_spell_tags("fly", "magia di 3 tier che permette di volare")
    assert out == "effect"
    assert man == "visible"


def test_invisibility_not_subtle_from_name() -> None:
    """'invisibil' must NOT force subtle — cast itself is visible to witnesses."""
    out, man = infer_spell_tags(
        "Invisibility",
        "magia di quarto tier che rende invisibile una creatura",
    )
    assert out == "effect"
    assert man == "visible"


def test_subtle_from_description() -> None:
    out, man = infer_spell_tags("Sense", "rileva minacce in modo passivo e mentale")
    assert out == "info"
    assert man == "subtle"


def test_occultamento_in_desc_does_not_force_subtle() -> None:
    out, man = infer_spell_tags(
        "Detect Power",
        "rileva forme di vita tranne barriere di occultamento",
    )
    assert out == "info"
    assert man == "visible"


def test_parse_and_format_roundtrip() -> None:
    line = format_spell_line(
        "Detect Power",
        "rileva aura",
        output="info",
        manifest="visible",
    )
    parsed = parse_spell_entry_line(line)
    assert parsed["name"] == "Detect Power"
    assert parsed["description"] == "rileva aura"
    assert parsed["output"] == "info"
    assert parsed["manifest"] == "visible"


def test_spellbook_backfill_writes_tags(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    path = wiki.spellbook_path("hero")
    path.write_text(
        "---\nid: hero-spellbook\nplayer_id: hero\ntype: spellbook\n---\n\n"
        "# Spellbook\n"
        "- Detect Power — rileva e identifica forme di vita\n"
        "- Fly — volare\n",
        encoding="utf-8",
    )
    spells = wiki.read_spellbook("Hero")
    by_name = {s["name"]: s for s in spells}
    assert by_name["Detect Power"]["output"] == "info"
    assert by_name["Fly"]["output"] == "effect"
    text = path.read_text(encoding="utf-8")
    assert "{info, visible}" in text
    assert "{effect, visible}" in text


def test_track_spells_preserves_existing_tags(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    wiki.track_spells(
        "Hero",
        {
            "Detect Power": {
                "description": "rileva",
                "output": "info",
                "manifest": "subtle",
            }
        },
    )
    wiki.track_spells("Hero", {"Detect Power": "rileva forme di vita"})
    spells = wiki.read_spellbook("Hero")
    assert spells[0]["output"] == "info"
    assert spells[0]["manifest"] == "subtle"
    assert "forme di vita" in spells[0]["description"]


def test_track_spells_does_not_clobber_ui_tags_with_model_defaults(
    tmp_path: Path,
) -> None:
    """Regression: NarrativeSpell defaults (effect/visible) must not wipe UI edits."""
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    wiki.track_spells("Hero", {"Detect Power": "rileva forme di vita"})
    wiki.set_spell_tags(
        "hero",
        [{"name": "Detect Power", "output": "info", "manifest": "subtle"}],
        player_name="Hero",
    )
    # Simulate commit_turn after a cast that re-sends default tags
    wiki.track_spells(
        "Hero",
        {
            "Detect Power": {
                "description": "rileva forme di vita",
                "output": "info",
                "manifest": "visible",  # model default — must be ignored
            }
        },
    )
    spells = wiki.read_spellbook("Hero")
    assert spells[0]["manifest"] == "subtle"
    assert spells[0]["output"] == "info"


def test_set_spell_tags(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    wiki.track_spells("Hero", {"Alert": "rileva minacce"})
    out = wiki.set_spell_tags(
        "hero",
        [{"name": "Alert", "output": "info", "manifest": "subtle"}],
        player_name="Hero",
    )
    assert out[0]["manifest"] == "subtle"
    assert out[0]["output"] == "info"
