"""Tests for player spellbook (separate from character sheet)."""

from pathlib import Path

import frontmatter

from app.services.wiki_writer import WikiWriter


def test_spellbook_add_and_update(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    wiki.track_spells("Hero", {"Fireball": "sfera di fuoco"})
    spells = wiki.read_spellbook("Hero")
    assert len(spells) == 1
    assert spells[0]["name"] == "Fireball"
    assert "fuoco" in spells[0]["description"]

    # use-only name → no duplicate
    wiki.track_spells("Hero", {"Fireball": ""})
    assert len(wiki.read_spellbook("Hero")) == 1

    # redefine with new description → modify
    wiki.track_spells("Hero", {"Fireball": "esplode al contatto"})
    spells = wiki.read_spellbook("Hero")
    assert len(spells) == 1
    assert "esplode" in spells[0]["description"]

    # sheet must not contain Incantesimi
    sheet = wiki.read_character("hero")
    assert "Incantesimi" not in sheet["body"]


def test_spellbook_dedupes_case_and_keeps_longest(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    path = wiki.spellbook_path("hero")
    path.write_text(
        "---\nid: hero-spellbook\nplayer_id: hero\ntype: spellbook\n---\n\n"
        "# Spellbook\n"
        "- detect power — corta\n"
        "- Detect Power — descrizione molto piu lunga e completa\n"
        "- Detect Power — media\n",
        encoding="utf-8",
    )
    spells = wiki.read_spellbook("Hero")
    detect = [s for s in spells if s["name"].lower() == "detect power"]
    assert len(detect) == 1
    assert "molto piu lunga" in detect[0]["description"]
    # file repaired
    text = path.read_text(encoding="utf-8")
    assert text.lower().count("detect power") == 1


def test_migrate_legacy_spells_from_sheet(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    path = wiki.ensure_player("Mage", "e-rantel")
    post = frontmatter.load(path)
    post.content = post.content.rstrip() + "\n\n# Incantesimi noti\n- Bolt — fulmine\n"
    path.write_text(frontmatter.dumps(post), encoding="utf-8")

    spells = wiki.read_spellbook("Mage")
    assert any(s["name"] == "Bolt" for s in spells)
    sheet = wiki.read_character("mage")
    assert "Bolt" not in sheet["body"]
    assert "Incantesimi" not in sheet["body"]
