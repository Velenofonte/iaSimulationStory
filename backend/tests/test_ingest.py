"""Tests for wiki ingest: normalization, pipeline, and generated markdown contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config import settings
from app.services.wiki_ingest_validate import (
    parse_wiki_page,
    section_body,
    validate_character_wiki,
    validate_markdown_structure,
    validate_world_wiki,
)
from scripts.fetch_sources import wiki_title_from_url, wikitext_to_plain
from scripts.ingest import CHARACTER_META, infer_template, main, normalize_ingest_output

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_WIKI = REPO_ROOT / "stories" / "overlord" / "wiki"


def _ingested_character_paths() -> list[Path]:
    sources = yaml.safe_load((REPO_ROOT / "sources.yaml").read_text(encoding="utf-8"))
    paths: list[Path] = []
    for entry in sources.get("characters", []):
        paths.append(SEED_WIKI / entry["out"])
    return sorted(paths)


INGESTED_CHARACTERS = _ingested_character_paths()

MALFORMED_LLM_GAZEF = """---
{}
---

```yaml
id: character_canonical
name: Gazef Stronoff
type: character
tier: canonical
```

# Personalità
Guerriero leale del regno.

# Aspetto fisico
Uomo muscoloso.

# Allineamento
Leale.

# Obiettivi
Proteggere il regno.

# Piani attuali
Difendere Carne.

# Capacità di combattimento
Spadaccino esperto.

# Arti marziali
- **Body Strengthening**: aumenta la forza muscolare.
- **Sixfold Slash of Light**: sei tagli in un colpo.

# Ki
Nessuna.

# Knowledge scope
sa: il regno
non sa: Ainz

# Relazione col giocatore
0

# Memorie

# Open threads
"""

MALFORMED_LLM_SEBAS = """---
{}
---

```yaml
id: character_canonical
name: Sebas Tian
type: character
tier: canonical
```

# Personalità
Maggiordomo leale.

# Aspetto fisico
Anziano elegante.

# Allineamento
Neutro buono.

# Obiettivi
Servire Ainz.

# Piani attuali
Intelligence a E-Rantel.

# Capacità di combattimento
Combattente disarmato di vertice.

## Skill / build YGGDRASIL
- Monk (10), Ki Master: Spiritual (15)

# Arti marziali
Nessuna. Non usa arti marziali del Nuovo Mondo.

# Ki
Utilizza Ki da monaco YGGDRASIL.

# Knowledge scope
sa: Nazarick
non sa: piani di Ainz

# Relazione col giocatore
0

# Memorie

# Open threads
"""


def _setup_ingest_tree(tmp_path: Path) -> tuple[Path, Path]:
    raw_dir = tmp_path / "raw" / "characters"
    raw_dir.mkdir(parents=True)
    wiki_dir = tmp_path / "stories" / "overlord" / "wiki" / "characters"
    wiki_dir.mkdir(parents=True)
    (tmp_path / "stories" / "overlord" / "meta.yaml").write_text("id: overlord\n", encoding="utf-8")
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "character_canonical.md").write_text(
        "---\nid: template\n---\n# Personalita\n", encoding="utf-8"
    )
    return raw_dir, wiki_dir


@pytest.mark.parametrize(
    ("url", "title"),
    [
        ("https://overlordmaruyama.fandom.com/wiki/Gazef_Stronoff", "Gazef_Stronoff"),
        ("https://overlordmaruyama.fandom.com/wiki/Martial_Arts", "Martial_Arts"),
    ],
)
def test_wiki_title_from_url(url: str, title: str) -> None:
    assert wiki_title_from_url(url) == title


def test_wikitext_to_plain_strips_markup() -> None:
    raw = "'''Bold''' [[Link|Label]] <ref>x</ref> [[Category:Foo]]"
    plain = wikitext_to_plain(raw)
    assert "Bold" in plain
    assert "Label" in plain
    assert "[[" not in plain
    assert "<ref" not in plain


class TestNormalizeIngestOutput:
    def test_fixes_code_fence_and_template_id(self) -> None:
        wiki_path = Path("characters/gazef.md")
        fixed = normalize_ingest_output(MALFORMED_LLM_GAZEF, wiki_path)
        errors = validate_character_wiki(fixed)
        assert errors == []
        meta, body = parse_wiki_page(fixed)
        assert meta["id"] == "gazef_stronoff"
        assert meta["name"] == "Gazef Stronoff"
        assert "Sixfold Slash of Light" in body

    def test_sebas_gets_correct_id(self) -> None:
        wiki_path = Path("characters/sebas.md")
        fixed = normalize_ingest_output(MALFORMED_LLM_SEBAS, wiki_path)
        meta, _ = parse_wiki_page(fixed)
        assert meta["id"] == "sebas_tian"
        assert validate_character_wiki(fixed) == []

    def test_momon_stem_keeps_momon_id_not_ainz(self) -> None:
        raw = """---
id: ainz_ooal_gown
name: Ainz Ooal Gown
type: character
tier: canonical
---

# Personalità
Alias.

# Aspetto fisico
Armatura.

# Allineamento
Neutro.

# Obiettivi
Fama.

# Capacità di combattimento
Spade.

# Arti marziali
Nessuna.

# Ki
Nessuna.

# Knowledge scope
sa: pubblico
non sa: nazarick

# Relazione col giocatore
0

# Memorie

# Open threads
"""
        fixed = normalize_ingest_output(raw, Path("characters/momon.md"))
        meta, _ = parse_wiki_page(fixed)
        assert meta["id"] == "momon"
        assert meta["name"] == "Momon"

    def test_world_page_from_yaml_fence(self) -> None:
        raw = """---
{}
---

```yaml
id: martial_arts
name: Arti Marziali
type: world
tier: canonical
source: https://overlordmaruyama.fandom.com/wiki/Martial_Arts
---
# Descrizione
Sistema del Nuovo Mondo.
```"""
        wiki_path = Path("world/martial-arts.md")
        fixed = normalize_ingest_output(raw, wiki_path)
        assert validate_world_wiki(fixed) == []
        meta, body = parse_wiki_page(fixed)
        assert meta["type"] == "world"
        assert "Nuovo Mondo" in body


def test_infer_template_paths() -> None:
    assert "character_canonical" in infer_template(Path("raw/characters/gazef.md"))
    assert "character_minimal" in infer_template(Path("raw/world/martial-arts.md"))


def test_ingest_main_writes_valid_character(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "project_root", tmp_path)
    raw_dir, wiki_dir = _setup_ingest_tree(tmp_path)
    (raw_dir / "gazef.md").write_text(
        "# Source: https://overlordmaruyama.fandom.com/wiki/Gazef_Stronoff\n\nWarrior captain.",
        encoding="utf-8",
    )

    from app.services import llm_client as llm_mod

    monkeypatch.setattr(llm_mod.LLMClient, "complete", lambda self, **kwargs: MALFORMED_LLM_GAZEF)

    main(force=True, only="gazef")

    out = wiki_dir / "gazef.md"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert validate_character_wiki(text) == []
    meta, _ = parse_wiki_page(text)
    assert meta["id"] == CHARACTER_META["gazef"]["id"]


def test_ingest_skips_existing_without_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "project_root", tmp_path)
    raw_dir, wiki_dir = _setup_ingest_tree(tmp_path)
    (raw_dir / "enri.md").write_text("# Source: https://example.com/enri\n\nVillager.", encoding="utf-8")
    existing = wiki_dir / "enri.md"
    existing.write_text("---\nid: enri_emmot\nname: Enri\ntype: character\ntier: canonical\n---\n\n# stub\n", encoding="utf-8")

    calls: list[str] = []

    from app.services import llm_client as llm_mod

    def _complete(self, **kwargs):
        calls.append("llm")
        return MALFORMED_LLM_GAZEF

    monkeypatch.setattr(llm_mod.LLMClient, "complete", _complete)
    main(force=False, only="enri")
    assert calls == []
    assert "stub" in existing.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", INGESTED_CHARACTERS, ids=lambda p: p.stem)
def test_seed_character_pages_are_valid(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"missing seed page {path.name}")
    text = path.read_text(encoding="utf-8")
    errors = validate_character_wiki(text)
    assert errors == [], f"{path.name}: {errors}"


def test_seed_gazef_has_martial_arts_techniques() -> None:
    path = SEED_WIKI / "characters" / "gazef.md"
    _, body = parse_wiki_page(path.read_text(encoding="utf-8"))
    section = section_body(body, "arti marziali").casefold()
    assert "sixfold slash of light" in section
    assert "body strengthening" in section


def test_seed_sebas_uses_ki_not_nw_martial_arts() -> None:
    path = SEED_WIKI / "characters" / "sebas.md"
    _, body = parse_wiki_page(path.read_text(encoding="utf-8"))
    ki = section_body(body, "ki").casefold()
    martial = section_body(body, "arti marziali").casefold()
    assert "ki" in ki
    assert "non utilizza ki" not in ki
    assert "nessuna" in martial or "non usa" in martial


def test_seed_martial_arts_world_page() -> None:
    path = SEED_WIKI / "world" / "martial-arts.md"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert validate_world_wiki(text) == []
    _, body = parse_wiki_page(text)
    lowered = body.casefold()
    assert "yggdrasil" in lowered
    assert "nuovo mondo" in lowered or "new world" in lowered


def test_sources_yaml_lists_martial_arts() -> None:
    sources = yaml.safe_load((REPO_ROOT / "sources.yaml").read_text(encoding="utf-8"))
    world_outs = [e["out"] for e in sources.get("world", [])]
    assert "world/martial-arts.md" in world_outs


def test_ingest_prompt_mentions_combat_systems() -> None:
    prompt = (settings.prompts_dir / "ingest.md").read_text(encoding="utf-8")
    assert "Arti marziali" in prompt
    assert "Ki" in prompt
    assert "code fence" in prompt.casefold() or "code fence" in prompt.lower()
