"""Tests for hybrid character sheet heading normalization."""

from __future__ import annotations

import re

from app.services.character_sheet_normalize import (
    has_nested_headings,
    normalize_character_body,
    promote_skill_build_headings,
)
from scripts.ingest import normalize_ingest_output


NESTED_SHALLTEAR = """# Capacita di combattimento
True Vampire di alto livello.

## Skill / build [[yggdrasil|YGGDRASIL]]
- Blood Frenzy
- Einherjar

# Arti marziali
Nessuna.
"""

WITH_PIANI = """# Personalita
Test.

# Piani attuali
Conquistare E-Rantel questa settimana.

# Knowledge scope
sa: poco
"""


def test_promote_skill_build_to_h1() -> None:
    out = promote_skill_build_headings(NESTED_SHALLTEAR)
    assert "## Skill" not in out
    assert "# Skill / build YGGDRASIL" in out
    assert "Blood Frenzy" in out


def test_normalize_flattens_other_nested_headings() -> None:
    body = "# Capacita\n\n## Tattiche\n- Veloce\n"
    out = normalize_character_body(body, seed=True)
    assert not has_nested_headings(out)
    assert "- **Tattiche**:" in out


def test_normalize_strips_piani_from_seed() -> None:
    out = normalize_character_body(WITH_PIANI, seed=True)
    assert "Piani attuali" not in out
    assert "Conquistare E-Rantel" not in out
    assert "Personalita" in out


def test_normalize_keeps_piani_when_not_seed() -> None:
    out = normalize_character_body(WITH_PIANI, seed=False)
    assert "Piani attuali" in out


def test_normalize_promotes_bold_bullet_sections() -> None:
    raw = """id: martin
name: Martin

# Martin

- **Aspetto fisico**:
- Capelli castani

- **Personalità**:
- Riservato

- **Capacità di combattimento**:
- Livello 100

# Skill / build YGGDRASIL
- Mago

- **Memorie**:
- *(vuoto)*
"""
    out = normalize_character_body(raw, seed=False)
    assert "id: martin" not in out
    assert not out.lstrip().startswith("# Martin")
    assert "# Aspetto fisico" in out
    assert "# Personalita" in out
    assert "# Capacita di combattimento" in out
    assert "# Memorie" in out
    assert "- **Aspetto fisico**:" not in out
    assert "Capelli castani" in out
    assert "vuoto" not in out.lower()


def test_normalize_strips_vuoto_placeholders() -> None:
    raw = """# Relazione col giocatore
- 0

# Memorie
- *(vuoto)*

# Open threads
- *(vuoto)*
"""
    out = normalize_character_body(raw, seed=False)
    assert "# Relazione col giocatore\n0\n" in out or "# Relazione col giocatore\n0" in out
    assert "vuoto" not in out.lower()
    assert re.search(r"# Memorie\s*\n\s*# Open threads", out)


def test_ingest_normalize_promotes_nested_skill() -> None:
    raw = """---
id: shalltear_bloodfallen
name: Shalltear
type: character
tier: canonical
---

# Personalità
Cruenta.

# Aspetto fisico
Bambina vampira.

# Allineamento
Malevolo.

# Obiettivi
Servire Ainz.

# Capacità di combattimento
Guardian.

## Skill / build YGGDRASIL
- Blood Frenzy

# Arti marziali
Nessuna.

# Ki
Nessuno.

# Knowledge scope
sa: Nazarick
non sa: mondo esterno

# Relazione col giocatore
0

# Memorie

# Open threads
"""
    fixed = normalize_ingest_output(raw, __import__("pathlib").Path("characters/shalltear.md"))
    assert "## " not in fixed.split("---", 2)[-1]
    assert "# Skill / build YGGDRASIL" in fixed
    assert "Piani attuali" not in fixed


def test_ingest_strips_piani_attuali() -> None:
    raw = """---
id: gazef_stronoff
name: Gazef
type: character
tier: canonical
---

# Personalità
Leale.

# Aspetto fisico
Guerriero.

# Allineamento
Buono.

# Obiettivi
Proteggere.

# Piani attuali
Difendere Carne.

# Capacità di combattimento
Spada.

# Arti marziali
Sixfold.

# Ki
Nessuna.

# Knowledge scope
sa: regno
non sa: Ainz

# Relazione col giocatore
0

# Memorie

# Open threads
"""
    fixed = normalize_ingest_output(raw, __import__("pathlib").Path("characters/gazef.md"))
    body = fixed.split("---", 2)[-1]
    assert "Piani attuali" not in body
    assert "Difendere Carne" not in body
