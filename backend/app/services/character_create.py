"""Generate a session player wiki sheet from race + freeform details."""

from __future__ import annotations

import re

import frontmatter

from app.config import settings
from app.services.character_sheet_normalize import normalize_character_body
from app.services.llm_client import LLMClient
from app.services.story_catalog import build_story_context, load_story_ingest_prompt
from app.services.wiki_writer import WikiWriter


_MOCK_BODY = """# Aspetto fisico
Aspetto coerente con la razza {race}; tratti non specificati lasciati generici.

# Personalita
{name} e' un avventuriero determinato, pronto a farsi strada nel Nuovo Mondo.

# Allineamento
Neutro.

# Obiettivo
Sopravvivere, capire le regole di questo mondo e perseguire i propri interessi.

# Capacita di combattimento
Competenze basate sui dettagli forniti; se assenti, livello da avventuriero competente.

# Skill / build YGGDRASIL
Nessuna.

# Arti marziali
Nessuna.

# Ki
Nessuno.

# Equipaggiamento
Equipaggiamento da avventuriero ordinario.

# Knowledge scope
sa: cio' che un individuo della sua origine conoscerebbe all'inizio.
non sa: segreti di Nazarick e trama nascosta del setting.

# Relazione col giocatore
0

# Memorie

# Open threads
"""


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _normalize_sheet(
    raw: str,
    *,
    character_id: str,
    name: str,
    location: str,
    race: str | None,
) -> tuple[dict, str]:
    text = _strip_code_fence(raw)
    if not text.lstrip().startswith("---"):
        # Model returned body only
        meta = {
            "id": character_id,
            "name": name,
            "type": "character",
            "tier": "minimal",
            "role": "player",
            "location": location,
        }
        if race:
            meta["race"] = race
        return meta, text.strip() + "\n"

    post = frontmatter.loads(text)
    meta = dict(post.metadata)
    meta["id"] = character_id
    meta["name"] = name
    meta["type"] = "character"
    meta["role"] = "player"
    meta["location"] = location
    meta.setdefault("tier", "minimal")
    if race:
        meta["race"] = race
    body = (post.content or "").strip()
    if not body:
        body = _MOCK_BODY.format(name=name, race=race or "sconosciuta").strip()
    # Drop spellbook-like sections; spells live in spellbook files
    for section in ("Spellbook", "Incantesimi noti", "Incantesimi"):
        body = WikiWriter._strip_section(body, section)
    body = normalize_character_body(body, seed=False)
    return meta, body.strip() + "\n"


def generate_custom_player_sheet(
    llm: LLMClient,
    *,
    story_id: str,
    name: str,
    race: str,
    details: str,
    location: str,
    character_id: str | None = None,
) -> tuple[dict, str]:
    cid = (character_id or WikiWriter.player_id(name)).strip()
    system = llm.load_prompt("character_create")
    story_rules = load_story_ingest_prompt(story_id)
    if story_rules:
        system = (
            f"{system.rstrip()}\n\n"
            f"## Regole aggiuntive della storia\n{story_rules}\n"
        )
    context = build_story_context(story_id)
    user = (
        f"STORY_CONTEXT:\n{context or '(nessuno)'}\n\n"
        f"CHARACTER_ID: {cid}\n"
        f"NAME: {name}\n"
        f"RACE: {race}\n"
        f"LOCATION: {location}\n"
        f"DETAILS:\n{(details or '').strip() or '(nessuno — completa tu in modo plausibile)'}\n"
    )
    raw = llm.complete(
        system=system,
        user=user,
        model=settings.llm_model_ingest or settings.llm_model_review,
        temperature=0.7,
    )
    return _normalize_sheet(raw, character_id=cid, name=name, location=location, race=race)


def extract_spells_from_body(body: str) -> dict[str, str]:
    """Best-effort: lines under magia-like sections as name — desc."""
    spells: dict[str, str] = {}
    section_re = re.compile(
        r"^#\s+(.*(?:magia|incantesimi|spell).*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(section_re.finditer(body))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[start:end]
        for line in chunk.splitlines():
            stripped = line.strip()
            if not stripped.startswith("-"):
                continue
            item = stripped.lstrip("- ").strip()
            if "—" in item:
                name, desc = item.split("—", 1)
            elif " - " in item:
                name, desc = item.split(" - ", 1)
            else:
                name, desc = item, ""
            name = name.strip()
            if name:
                spells[name] = desc.strip()
    return spells
