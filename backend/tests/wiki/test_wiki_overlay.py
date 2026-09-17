"""Tests for arc wiki overlays: merge, isolation, invariant combat sections."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from app.models import FrontRuntime, GameState, PlayerState
from app.services.prompt_builder import PromptBuilder
from app.services.wiki_overlay import (
    merge_section_bodies,
    validate_overlay_body,
)
from app.services.wiki_query import WikiQuery
from app.services.save_manager import SaveManager
from tests.conftest import make_seed_story


def _write_base_and_overlay(wiki: Path) -> None:
    (wiki / "characters").mkdir(parents=True, exist_ok=True)
    (wiki / "overlays" / "carne_arc" / "characters").mkdir(parents=True, exist_ok=True)
    (wiki / "characters" / "ainz.md").write_text(
        "---\nid: ainz_ooal_gown\nname: Ainz Ooal Gown\ntype: character\ntier: canonical\n---\n\n"
        "# Personalità\nCalcolatore.\n\n"
        "# Capacità di combattimento\nIncantatore livello 100; forza sproporzionata.\n\n"
        "# Knowledge scope\nsa: magia\nnon sa: futuro\n",
        encoding="utf-8",
    )
    (wiki / "overlays" / "carne_arc" / "characters" / "ainz.md").write_text(
        "---\nid: ainz\narc: carne_arc\nextends: ainz\nrole: mago misterioso\n---\n\n"
        "# Titoli validi\nAinz Ooal Gown; non Re Stregone.\n\n"
        "# Knowledge scope\nsa: Nazarick, Carne\nnon sa: Regno Stregone\n",
        encoding="utf-8",
    )
    (wiki / "index.md").write_text(
        "# Index\n\n## Characters\n- [[ainz]] -> characters/ainz.md\n",
        encoding="utf-8",
    )


def test_merge_replaces_named_sections_keeps_combat() -> None:
    base = (
        "# Personalità\nBase.\n\n"
        "# Capacità di combattimento\nMagia 100.\n\n"
        "# Knowledge scope\nsa: tutto\n"
    )
    overlay = (
        "# Titoli validi\nMago oscuro.\n\n"
        "# Knowledge scope\nsa: solo Carne\n\n"
        "# Capacità di combattimento\nNON DEVE COMPARIRE\n"
    )
    merged = merge_section_bodies(base, overlay)
    assert "Magia 100" in merged
    assert "NON DEVE COMPARIRE" not in merged
    assert "Mago oscuro" in merged
    assert "solo Carne" in merged
    assert "tutto" not in merged


def test_validate_overlay_rejects_combat_section() -> None:
    errors = validate_overlay_body("# Capacità di combattimento\nx\n")
    assert errors
    assert validate_overlay_body("# Titoli validi\nAinz\n") == []


def test_overlay_excluded_from_aliases(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _write_base_and_overlay(wiki)
    # Poison: overlay-only name must not resolve as standalone page
    post = frontmatter.load(wiki / "overlays" / "carne_arc" / "characters" / "ainz.md")
    post.metadata["name"] = "UniqueOverlayOnlyName"
    (wiki / "overlays" / "carne_arc" / "characters" / "ainz.md").write_text(
        frontmatter.dumps(post), encoding="utf-8"
    )
    q = WikiQuery(wiki_dir=wiki)
    assert q.resolve_id("ainz") == wiki / "characters" / "ainz.md"
    assert q.resolve_id("UniqueOverlayOnlyName") is None


def test_load_character_merges_active_arc(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _write_base_and_overlay(wiki)
    q = WikiQuery(wiki_dir=wiki)
    bare = q.load_character("ainz")
    assert bare is not None
    assert "Re Stregone" not in bare.body or "Titoli validi" not in bare.body
    assert "Magia 100" in bare.body or "Incantatore" in bare.body

    merged = q.load_character("ainz", active_arc_ids=["carne_arc"])
    assert merged is not None
    assert "Titoli validi" in merged.body
    assert "non Re Stregone" in merged.body
    assert "Incantatore livello 100" in merged.body
    assert "Regno Stregone" in merged.body  # in non sa
    assert merged.role == "mago misterioso"


def test_seed_ainz_carne_overlay_no_sorcerer_king_title() -> None:
    root = Path(__file__).resolve().parents[3]
    seed = root / "stories" / "overlord" / "wiki"
    if not (seed / "overlays" / "carne_arc" / "characters" / "ainz.md").exists():
        pytest.skip("seed overlay missing")
    q = WikiQuery(wiki_dir=seed)
    card = q.load_character("ainz", active_arc_ids=["carne_arc"])
    assert card is not None
    text = PromptBuilder().build_prompt_card(card)
    assert "Titoli validi" in text or "non Re Stregone" in card.body
    body_fold = card.body.casefold()
    assert (
        "capacità di combattimento" in body_fold
        or "capacita di combattimento" in body_fold
    )
    # Title ban present; combat retained
    assert "Re Stregone" in card.body  # mentioned as forbidden
    assert "Vietati" in card.body or "non Re Stregone" in card.body.casefold() or "non è" in card.body.casefold()


def test_save_clones_overlays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    stories = make_seed_story(tmp_path)
    seed_wiki = stories / "wiki"
    overlay = seed_wiki / "overlays" / "carne_arc" / "characters"
    overlay.mkdir(parents=True)
    (overlay / "ainz.md").write_text(
        "---\nid: ainz\narc: carne_arc\nextends: ainz\n---\n\n# Titoli validi\nAinz.\n",
        encoding="utf-8",
    )
    (seed_wiki / "characters" / "ainz.md").write_text(
        "---\nid: ainz\nname: Ainz\ntype: character\ntier: canonical\n---\n\n"
        "# Capacità di combattimento\nLv100.\n",
        encoding="utf-8",
    )
    saves = SaveManager(root=tmp_path / "saves")
    state = saves.create_session("Hero", start_location="carne", story_id="overlord")
    cloned = saves.wiki_dir(state.session_id) / "overlays" / "carne_arc" / "characters" / "ainz.md"
    assert cloned.exists()
    state.fronts["carne_arc"] = FrontRuntime(id="carne_arc", status="active", cursor_beat="x")
    q = WikiQuery(wiki_dir=saves.wiki_dir(state.session_id))
    card = q.load_character("ainz", active_arc_ids=["carne_arc"])
    assert card is not None
    assert "Titoli validi" in card.body
    assert "Lv100" in card.body


def test_character_first_name_and_aka_aliases(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    (wiki / "characters").mkdir(parents=True)
    (wiki / "characters" / "lizzie-bareare.md").write_text(
        "---\nid: lizzie_bareare\nname: Lizzie Bareare\ntype: character\ntier: canonical\n"
        "aka: [lizzy]\n---\n\n# Personalita\nAcuta.\n",
        encoding="utf-8",
    )
    (wiki / "index.md").write_text(
        "# Index\n\n## Characters\n- [[lizzie-bareare]] -> characters/lizzie-bareare.md\n",
        encoding="utf-8",
    )
    q = WikiQuery(wiki_dir=wiki)
    target = wiki / "characters" / "lizzie-bareare.md"
    assert q.resolve_id("lizzie") == target
    assert q.resolve_id("lizzy") == target
    assert q.resolve_id("Lizzie Bareare") == target
