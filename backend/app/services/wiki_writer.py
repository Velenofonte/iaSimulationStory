from datetime import datetime, timezone
from pathlib import Path
import re

import frontmatter

from app.config import settings
from app.models import ConsolidationReviewResult, EntityCreate
from app.models.narrative import split_spell_line
from app.services.character_sheet_normalize import (
    needs_sheet_normalize,
    normalize_character_body,
)


class WikiWriter:
    def __init__(self, wiki_dir: Path | None = None) -> None:
        self.wiki_dir = wiki_dir or settings.wiki_dir
        for sub in ("world", "locations", "characters", "factions", "parties", "spellbooks"):
            (self.wiki_dir / sub).mkdir(parents=True, exist_ok=True)
        self.index_path = self.wiki_dir / "index.md"

    def apply_entity_patches(
        self,
        patches: list[dict],
    ) -> None:
        """Apply deterministic wiki writes from arc beats (no LLM).

        Each patch: {"entity": id, "events_add": [...], "tensions_add": [...]}.
        """
        for patch in patches:
            entity_id = str(patch.get("entity") or "").strip()
            if not entity_id:
                continue
            path = self._resolve_entity_path(entity_id)
            if not path:
                continue
            post = frontmatter.load(path)
            body = post.content
            events = patch.get("events_add") or []
            tensions = patch.get("tensions_add") or []
            if events:
                body = self._append_section_lines(body, "Eventi", [str(x) for x in events])
            if tensions:
                body = self._append_section_lines(body, "Tensioni", [str(x) for x in tensions])
            post.content = body
            path.write_text(frontmatter.dumps(post), encoding="utf-8")

    def ensure_location(
        self,
        location_id: str,
        *,
        name: str | None = None,
        kind: str = "default",
        danger: str = "medium",
        body: str | None = None,
    ) -> Path:
        """Create a minimal location stub if missing (runtime session wiki)."""
        lid = (location_id or "").strip().lower().replace("_", "-")
        if not lid:
            raise ValueError("location_id required")
        path = self.wiki_dir / "locations" / f"{lid}.md"
        if path.exists():
            return path
        display = (name or lid.replace("-", " ").title()).strip()
        metadata = {
            "id": lid,
            "name": display,
            "type": "location",
            "tier": "minimal",
            "kind": (kind or "default").strip().lower() or "default",
            "danger": (danger or "medium").strip().lower() or "medium",
            "source": "runtime",
        }
        content = (body or "").strip() or (
            f"# Descrizione\nLuogo emerso in sessione: {display}.\n\n"
            f"# Ruolo\nContesto locale; da espandere in gioco.\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            frontmatter.dumps(frontmatter.Post(content if content.endswith("\n") else content + "\n", **metadata)),
            encoding="utf-8",
        )
        self._add_index(lid, f"locations/{lid}.md")
        return path

    def list_location_ids(self) -> list[str]:
        """Ids of location pages in the current wiki."""
        folder = self.wiki_dir / "locations"
        if not folder.is_dir():
            return []
        return sorted(p.stem for p in folder.glob("*.md"))

    def write_notoriety_section(self, character_id: str, lines: list[str]) -> None:
        """Replace the runtime-only # Notorieta section on a character sheet."""
        path = self._character_path(character_id)
        if not path.exists():
            return
        post = frontmatter.load(path)
        value = "\n".join(f"- {line}" for line in lines) if lines else ""
        post.content = self.set_section(post.content, "Notorieta", value)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

    def apply_consolidation(self, result: ConsolidationReviewResult) -> None:
        for entity in result.create_entities:
            self.create_entity(entity)
        for character_id, update in result.character_updates.items():
            path = self._character_path(character_id)
            if not path.exists():
                continue
            post = frontmatter.load(path)
            body = post.content
            if update.memories_remove:
                body = self._remove_section_lines(body, "Memorie", update.memories_remove)
            if update.memories_add:
                body = self._append_section_lines(body, "Memorie", update.memories_add)
            if getattr(update, "spells_add", None):
                # Spells live in spellbook, not character sheet
                spell_map: dict[str, str] = {}
                for line in update.spells_add:
                    name, desc = split_spell_line(line)
                    if name:
                        spell_map[name] = desc
                if spell_map:
                    self.track_spells_for_id(character_id, spell_map)
            if update.open_threads_remove:
                body = self._remove_section_lines(body, "Open threads", update.open_threads_remove)
            if update.open_threads_add:
                body = self._append_section_lines(body, "Open threads", update.open_threads_add)
            if update.relationship is not None or update.relationship_summary_add:
                body = self._merge_relationship_section(
                    body,
                    score=update.relationship,
                    summary_add=list(update.relationship_summary_add or []),
                )
            if update.promote_tier:
                post.metadata["tier"] = update.promote_tier
            if update.location:
                post.metadata["location"] = update.location
            if update.party_id:
                post.metadata["party"] = update.party_id
            for section, lines in (update.sections_add or {}).items():
                if lines:
                    # Keep spells out of character sheet even via sections_add
                    if section.strip().lower() in {"incantesimi noti", "incantesimi", "spellbook"}:
                        continue
                    body = self._append_section_lines(body, section, lines)
            post.content = body
            path.write_text(frontmatter.dumps(post), encoding="utf-8")

        place_updates = {**result.location_updates, **result.world_updates}
        for entity_id, update in place_updates.items():
            path = self._resolve_entity_path(entity_id)
            if not path:
                continue
            post = frontmatter.load(path)
            body = post.content
            if update.events_add:
                body = self._append_section_lines(body, "Eventi", update.events_add)
            if update.tensions_add:
                body = self._append_section_lines(body, "Tensioni", update.tensions_add)
            for section, lines in (update.sections_add or {}).items():
                if lines:
                    body = self._append_section_lines(body, section, lines)
            post.content = body
            path.write_text(frontmatter.dumps(post), encoding="utf-8")

    def _resolve_entity_path(self, entity_id: str) -> Path | None:
        key = entity_id.strip().lower().replace(" ", "-").replace("_", "-")
        for folder in ("locations", "nations", "world", "factions", "characters"):
            path = self.wiki_dir / folder / f"{key}.md"
            if path.exists():
                return path
            # fallback: stem match with underscores
            alt = self.wiki_dir / folder / f"{entity_id.strip().lower().replace(' ', '_')}.md"
            if alt.exists():
                return alt
        # last resort: any matching stem
        matches = list(self.wiki_dir.rglob(f"{key}.md"))
        return matches[0] if matches else None

    def create_entity(self, entity: EntityCreate) -> Path:
        folder = {
            "character": "characters",
            "party": "parties",
            "location": "locations",
            "faction": "factions",
        }[entity.type]
        path = self.wiki_dir / folder / f"{entity.id}.md"
        if path.exists():
            return path
        metadata = {
            "id": entity.id,
            "name": entity.name,
            "type": "generated",
            "tier": "minimal" if entity.type == "character" else "growing",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data = dict(entity.data)
        body = data.pop("body", f"# {entity.name}\n")
        metadata.update(data)
        path.write_text(frontmatter.dumps(frontmatter.Post(body, **metadata)), encoding="utf-8")
        self._add_index(entity.id, f"{folder}/{entity.id}.md")
        return path

    def create_npc_from_template(
        self,
        *,
        entity_id: str,
        name: str,
        role: str,
        location: str,
        template: str,
        body: str,
    ) -> Path:
        entity = EntityCreate(
            type="character",
            id=entity_id,
            name=name,
            data={
                "role": role,
                "location": location,
                "template": template,
                "body": body,
            },
        )
        return self.create_entity(entity)

    @staticmethod
    def player_id(name: str) -> str:
        return name.lower().replace(" ", "-")

    def ensure_player(
        self,
        name: str,
        location: str,
        *,
        character_id: str | None = None,
    ) -> Path:
        pid = (character_id or self.player_id(name)).strip()
        path = self._character_path(pid)
        if path.exists():
            return path
        body = (
            "# Personalita\n\n"
            "# Aspetto fisico\n\n"
            "# Obiettivi\n\n"
            "# Knowledge scope\nsa:\nnon sa:\n\n"
            "# Memorie\n\n"
            "# Open threads\n"
        )
        return self.create_entity(
            EntityCreate(
                type="character",
                id=pid,
                name=name,
                data={"role": "player", "location": location, "body": body},
            )
        )

    def bind_as_player(
        self,
        character_id: str,
        *,
        location: str | None = None,
    ) -> dict:
        """Mark an existing session wiki sheet as the controlled player (lore path)."""
        path = self._character_path(character_id)
        if not path.exists():
            raise FileNotFoundError(character_id)
        post = frontmatter.load(path)
        post.metadata["role"] = "player"
        if location:
            post.metadata["location"] = location
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return self.read_character(character_id)

    def write_player_sheet(
        self,
        *,
        character_id: str,
        name: str,
        location: str,
        body: str,
        race: str | None = None,
        tier: str = "minimal",
    ) -> Path:
        path = self._character_path(character_id)
        metadata: dict = {
            "id": character_id,
            "name": name,
            "type": "character",
            "tier": tier,
            "role": "player",
            "location": location,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if race:
            metadata["race"] = race
        path.parent.mkdir(parents=True, exist_ok=True)
        clean_body = normalize_character_body(body, seed=False)
        path.write_text(
            frontmatter.dumps(frontmatter.Post(clean_body.strip() + "\n", **metadata)),
            encoding="utf-8",
        )
        self._add_index(character_id, f"characters/{character_id}.md")
        return path

    def read_character(self, character_id: str) -> dict:
        path = self._character_path(character_id)
        if not path.exists():
            raise FileNotFoundError(character_id)
        post = frontmatter.load(path)
        body = self._strip_section(post.content, "Incantesimi noti")
        # Schede custom/LLM (es. DeepSeek) spesso usano `- **Sezione**:` invece di `#`.
        if needs_sheet_normalize(body):
            healed = normalize_character_body(body, seed=False)
            if healed.strip() != (body or "").strip():
                post.content = healed
                path.write_text(frontmatter.dumps(post), encoding="utf-8")
            body = healed
        meta = post.metadata or {}
        job = meta.get("job") or meta.get("classes")
        if isinstance(job, list):
            job = ", ".join(str(x) for x in job)
        return {
            "id": str(meta.get("id", character_id)),
            "name": str(meta.get("name", character_id)),
            "role": meta.get("role"),
            "location": meta.get("location"),
            "race": meta.get("race"),
            "job": job,
            "affiliation": meta.get("affiliation"),
            "residence": meta.get("residence"),
            "level": meta.get("level"),
            "body": body.strip(),
        }

    def spellbook_path(self, player_id: str) -> Path:
        return self.wiki_dir / "spellbooks" / f"{player_id}.md"

    def ensure_spellbook(
        self,
        player_name: str,
        *,
        character_id: str | None = None,
    ) -> Path:
        pid = (character_id or self.player_id(player_name)).strip()
        path = self.spellbook_path(pid)
        if path.exists():
            existing = self.read_spellbook(player_name, character_id=pid, ensure=False)
            if existing:
                return path
            hydrated = self._extract_spells_from_character(pid)
            if hydrated:
                self._write_spellbook_lines(path, player_name, pid, hydrated)
            return path

        migrated_map: dict[str, str] = {}
        char_path = self._character_path(pid)
        if char_path.exists():
            post = frontmatter.load(char_path)
            for line in self.get_section(post.content, "Incantesimi noti"):
                name, desc = split_spell_line(line)
                if name:
                    migrated_map[name] = desc
            if migrated_map:
                cleaned = self._strip_section(post.content, "Incantesimi noti")
                post.content = cleaned
                char_path.write_text(frontmatter.dumps(post), encoding="utf-8")
        hydrated = self._extract_spells_from_character(pid)
        spells = {**hydrated, **migrated_map}
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_spellbook_lines(path, player_name, pid, spells)
        return path

    def _write_spellbook_lines(
        self,
        path: Path,
        player_name: str,
        player_id: str,
        spells: dict[str, str],
    ) -> None:
        body = "# Spellbook\n"
        if spells:
            body += (
                "\n".join(
                    f"- {name} — {desc}" if desc else f"- {name}"
                    for name, desc in spells.items()
                )
                + "\n"
            )
        meta = {
            "id": f"{player_id}-spellbook",
            "player_id": player_id,
            "name": f"Spellbook di {player_name}",
            "type": "spellbook",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frontmatter.dumps(frontmatter.Post(body, **meta)), encoding="utf-8")

    def _extract_spells_from_character(self, character_id: str) -> dict[str, str]:
        """Pull lore spells from sheet sections / [Bracket] skill markers."""
        path = self._character_path(character_id)
        if not path.exists():
            return {}
        post = frontmatter.load(path)
        body = post.content or ""
        out: dict[str, str] = {}
        for section in ("Incantesimi noti", "Incantesimi", "Magie", "Magia"):
            for line in self.get_section(body, section):
                name, desc = split_spell_line(line)
                if name:
                    out[name] = desc
        for match in re.finditer(r"\[([^\[\]]{2,60})\]", body):
            name = match.group(1).strip()
            if not name:
                continue
            out.setdefault(name, "")
        return out

    def read_spellbook(
        self,
        player_name: str,
        *,
        character_id: str | None = None,
        ensure: bool = True,
    ) -> list[dict[str, str]]:
        """Return [{name, description}, ...] deduped by case-insensitive name."""
        pid = (character_id or self.player_id(player_name)).strip()
        if ensure:
            self.ensure_spellbook(player_name, character_id=pid)
        path = self.spellbook_path(pid)
        if not path.exists():
            return []
        post = frontmatter.load(path)
        lines = self.get_section(post.content, "Spellbook")
        if not lines:
            lines = [
                line.strip("- ").strip()
                for line in post.content.splitlines()
                if line.strip().startswith("-")
            ]
        by_key: dict[str, dict[str, str]] = {}
        order: list[str] = []
        for line in lines:
            name, desc = split_spell_line(line)
            if not name:
                continue
            key = name.lower()
            prev = by_key.get(key)
            # Prefer longer description when collapsing duplicates
            if prev is None:
                by_key[key] = {"name": name, "description": desc}
                order.append(key)
            elif len(desc) > len(prev.get("description") or ""):
                by_key[key] = {"name": name, "description": desc}
        spells = [by_key[k] for k in order]
        # Persist repair if file had duplicates
        if len(lines) > len(spells):
            body = "# Spellbook\n" + "\n".join(
                f"- {s['name']} — {s['description']}" if s["description"] else f"- {s['name']}"
                for s in spells
            ) + "\n"
            post.content = body
            path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return spells

    def track_spells(
        self,
        player_name: str,
        spells: dict[str, str],
        *,
        character_id: str | None = None,
    ) -> None:
        """Add/update spells in the player's spellbook (not character sheet)."""
        pid = (character_id or self.player_id(player_name)).strip()
        self.track_spells_for_id(pid, spells, player_name=player_name)

    def track_spells_for_id(
        self,
        player_id: str,
        spells: dict[str, str],
        *,
        player_name: str | None = None,
    ) -> None:
        name = player_name or player_id
        self.ensure_spellbook(name, character_id=player_id)
        path = self.spellbook_path(player_id)
        if not path.exists():
            path = self.spellbook_path(self.player_id(name))
        post = frontmatter.load(path)
        body = post.content
        existing = self.get_section(body, "Spellbook")
        by_name: dict[str, str] = {}
        order: list[str] = []
        for line in existing:
            n, d = split_spell_line(line)
            key = n.lower()
            if not key:
                continue
            entry = f"{n} — {d}" if d else n
            prev = by_name.get(key)
            if prev is None:
                by_name[key] = entry
                order.append(key)
            else:
                # keep longer description
                prev_desc = split_spell_line(prev)[1]
                if len(d) > len(prev_desc):
                    by_name[key] = entry

        changed = False
        for spell_name, desc in spells.items():
            key = spell_name.strip().lower()
            if not key:
                continue
            if key in by_name:
                if desc.strip():
                    by_name[key] = f"{spell_name.strip()} — {desc.strip()}"
                    changed = True
            else:
                by_name[key] = (
                    f"{spell_name.strip()} — {desc.strip()}" if desc.strip() else spell_name.strip()
                )
                order.append(key)
                changed = True

        # Always rewrite if duplicates were collapsed from existing
        unique_existing = len({split_spell_line(x)[0].lower() for x in existing if x.strip()})
        if len(existing) > unique_existing:
            changed = True

        if not changed:
            return
        lines = [by_name[k] for k in order]
        post.content = self.set_section(body, "Spellbook", "\n".join(f"- {line}" for line in lines))
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

    def _character_path(self, character_id: str) -> Path:
        return self.wiki_dir / "characters" / f"{character_id}.md"

    @staticmethod
    def _strip_section(body: str, section: str) -> str:
        marker = f"# {section}"
        if marker not in body:
            return body
        before, rest = body.split(marker, 1)
        next_hash = rest.find("\n# ")
        after = "" if next_hash == -1 else rest[next_hash:]
        return (before.rstrip() + "\n\n" + after.lstrip()).strip() + "\n"

    def _add_index(self, entity_id: str, rel_path: str) -> None:
        rel_norm = rel_path.replace("\\", "/")
        if rel_norm.startswith("overlays/"):
            return
        line = f"- [[{entity_id}]] -> {rel_norm}"
        section = self._section_for_path(rel_norm)
        if not self.index_path.exists():
            self.index_path.write_text("# Wiki Index\n\n", encoding="utf-8")
        content = self.index_path.read_text(encoding="utf-8")
        if f"[[{entity_id}]]" in content:
            return
        marker = f"## {section}"
        if marker not in content:
            content = content.rstrip() + f"\n\n{marker}\n"
        before, rest = content.split(marker, 1)
        next_header = rest.find("\n## ")
        if next_header == -1:
            section_body, after = rest, ""
        else:
            section_body, after = rest[:next_header], rest[next_header:]
        section_body = section_body.rstrip() + f"\n{line}\n"
        self.index_path.write_text(f"{before}{marker}{section_body}{after}", encoding="utf-8")

    @staticmethod
    def _section_for_path(rel_path: str) -> str:
        folder = rel_path.replace("\\", "/").split("/", 1)[0]
        return {
            "characters": "Characters",
            "locations": "Locations",
            "nations": "Nations",
            "factions": "Factions",
            "parties": "Parties",
            "spellbooks": "Spellbooks",
            "world": "World",
        }.get(folder, "Other")

    def rebuild_index(self) -> None:
        sections: dict[str, list[str]] = {
            "Characters": [],
            "Locations": [],
            "Nations": [],
            "Factions": [],
            "Parties": [],
            "Spellbooks": [],
            "World": [],
            "Other": [],
        }
        for path in sorted(self.wiki_dir.rglob("*.md")):
            if path.name == "index.md":
                continue
            rel = path.relative_to(self.wiki_dir).as_posix()
            if rel.startswith("overlays/"):
                continue
            entity_id = path.stem
            sections[self._section_for_path(rel)].append(f"- [[{entity_id}]] -> {rel}")
        parts = ["# Wiki Index\n"]
        for name, lines in sections.items():
            if not lines:
                continue
            parts.append(f"## {name}")
            parts.extend(lines)
            parts.append("")
        self.index_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")

    def _append_section_lines(self, body: str, section: str, lines: list[str]) -> str:
        existing = self.get_section(body, section)
        merged = list(existing)
        for line in lines:
            if not line.strip():
                continue
            merged = self._merge_bullet_list(merged, line)
        return self.set_section(body, section, "\n".join(f"- {line}" for line in merged))

    def _merge_relationship_section(
        self,
        body: str,
        *,
        score: int | None = None,
        summary_add: list[str] | None = None,
    ) -> str:
        """Merge score + dense encounter bullets into Relazione col giocatore."""
        section = "Relazione col giocatore"
        raw = self._get_section_raw(body, section)
        existing_bullets = self.get_section(body, section)
        current_score: int | None = None
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("punteggio:"):
                try:
                    current_score = int(stripped.split(":", 1)[1].strip())
                except ValueError:
                    pass
                break
            if stripped.isdigit():
                current_score = int(stripped)
                break

        if score is not None:
            current_score = int(score)

        bullets = list(existing_bullets)
        for line in summary_add or []:
            if line.strip():
                bullets = self._merge_bullet_list(bullets, line)

        parts: list[str] = []
        if current_score is not None:
            parts.append(f"Punteggio: {current_score}")
        if bullets:
            parts.extend(f"- {b}" for b in bullets)
        if not parts and score is not None:
            parts.append(f"Punteggio: {score}")
        return self.set_section(body, section, "\n".join(parts))

    def _get_section_raw(self, body: str, section: str) -> str:
        marker = f"# {section}"
        if marker not in body:
            return ""
        part = body.split(marker, 1)[1]
        next_hash = part.find("\n# ")
        chunk = part if next_hash == -1 else part[:next_hash]
        return chunk.strip()

    def _remove_section_lines(self, body: str, section: str, lines: list[str]) -> str:
        existing = self.get_section(body, section)
        if not existing or not lines:
            return body
        remove_norms = {self._norm_bullet(x) for x in lines if x.strip()}
        kept: list[str] = []
        for line in existing:
            n = self._norm_bullet(line)
            if n in remove_norms:
                continue
            # Match substring for paraphrases / shortened remove targets
            if any(len(r) >= 24 and (r in n or n in r) for r in remove_norms):
                continue
            kept.append(line)
        value = "\n".join(f"- {line}" for line in kept) if kept else ""
        return self.set_section(body, section, value)

    @classmethod
    def _merge_bullet_list(cls, existing: list[str], new_line: str) -> list[str]:
        """Append new_line, absorbing exact/prefix duplicates (keep the denser line)."""
        n = cls._norm_bullet(new_line)
        if not n:
            return list(existing)
        out: list[str] = []
        absorbed = False
        for old in existing:
            o = cls._norm_bullet(old)
            if not o:
                continue
            if o == n:
                # Prefer longer / denser wording
                out.append(new_line if len(n) >= len(o) else old)
                absorbed = True
                continue
            if len(o) >= 24 and o in n:
                # New line extends an older shorter memory → replace
                if not absorbed:
                    out.append(new_line)
                    absorbed = True
                continue
            if len(n) >= 24 and n in o:
                # Existing already covers the new fact → keep existing
                out.append(old)
                absorbed = True
                continue
            out.append(old)
        if not absorbed:
            out.append(new_line)
        return out

    @staticmethod
    def _norm_bullet(line: str) -> str:
        return " ".join(line.lower().split())

    def get_section(self, body: str, section: str) -> list[str]:
        marker = f"# {section}"
        if marker not in body:
            return []
        part = body.split(marker, 1)[1]
        next_hash = part.find("\n# ")
        chunk = part if next_hash == -1 else part[:next_hash]
        return [line.strip("- ").strip() for line in chunk.splitlines() if line.strip().startswith("-")]

    def set_section(self, body: str, section: str, value: str) -> str:
        marker = f"# {section}"
        if marker in body:
            before, rest = body.split(marker, 1)
            next_hash = rest.find("\n# ")
            after = "" if next_hash == -1 else rest[next_hash:]
            # Keep a trailing newline before the next section
            gap = "\n" if value and not value.endswith("\n") else ""
            return f"{before}{marker}\n{value}{gap}{after}"
        return body.rstrip() + f"\n\n# {section}\n{value}\n"
