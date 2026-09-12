import re
import unicodedata
from pathlib import Path

import frontmatter

from app.config import settings
from app.models import CharacterCard, GameState
from app.services.wiki_overlay import (
    is_overlay_path,
    merge_character_with_overlays,
    overlay_path,
    resolve_overlay_stems,
)


WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z0-9_-]+\b")
# Cast magia: [Spell] / [Spell — desc], non [[wiki links]]
_SPELL_CAST_RE = re.compile(r"(?<!\[)\[([^\[\]]+)\](?!\])")

# Lore comune avventurieri (ibrido B): topic messaggio / presenti / link location
_ADVENTURER_TOPIC_RE = re.compile(
    r"(?i)\b("
    r"gilda|rangh[ioie]?|grad[ioe]|piastrin\w*|"
    r"avventurier\w*|adventurer\w*|"
    r"copper|ferro\b|iron\b|silver|argento|"
    r"mithril|mitril|oricalc\w*|orichalc\w*|"
    r"adamantit\w*|platino|platinum"
    r")\b"
)
_ADVENTURER_PRESENT_RE = re.compile(r"(?i)avventurier|adventurer")
_ADVENTURER_LORE_IDS = ("adventurer", "adventurers_guild", "adventurers-guild")
_MAGIC_TIER_LORE_IDS = ("magic-tier", "magic_tier", "tier_magic", "tier-magic")
# Sezioni da tenere in testa nell'excerpt (altrimenti WORLD_EXCERPT_CHARS le taglia).
_EXCERPT_PRIORITY_TITLE_RE = re.compile(
    r"(?i)^#\s*(Gerarchia|Hierarchy|Ranghi|Rank|Scala dei tier|Lista di Tier)"
)
_MAGIC_TIER_ANCHOR_RE = re.compile(
    r"(?i)(?:Lista di Tier Magic|#\s*Scala dei tier|0°\s*Tier|0\s*Tier)",
)


def build_world_excerpt(
    body: str,
    cap: int,
    *,
    entity_id: str = "",
) -> str:
    """Appiattisce il body e rispetta cap; per lore ranghi/tier antepone sezioni utili."""
    text = (body or "").strip()
    if not text:
        return ""
    eid = (entity_id or "").lower().replace("-", "_")
    prefer_adventurer = eid in {
        "adventurer",
        "adventurers_guild",
        "adventurersguild",
    } or eid.startswith("adventurer")
    prefer_magic = (
        eid in {
            "magic_tier",
            "magictier",
            "tier_magic",
            "tiermagic",
        }
        or ("magic" in eid and "tier" in eid)
        or eid.startswith("tier_magic")
    )
    if prefer_adventurer or prefer_magic:
        sections = [s.strip() for s in re.split(r"(?m)(?=^# )", text) if s.strip()]
        if sections:
            priority: list[str] = []
            rest: list[str] = []
            for sec in sections:
                title = sec.split("\n", 1)[0]
                if _EXCERPT_PRIORITY_TITLE_RE.search(title):
                    priority.append(sec)
                else:
                    rest.append(sec)
            if priority:
                text = "\n\n".join(priority + rest)
        if prefer_magic:
            # Pagina legacy con ### / junk in testa: salta alla lista tier
            anchor = _MAGIC_TIER_ANCHOR_RE.search(text)
            if anchor and anchor.start() > 0:
                text = text[anchor.start() :]
    flat = text.replace("\n", " ")
    if cap > 0:
        return flat[:cap]
    return flat


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text).strip("-")


class WikiQuery:
    def __init__(self, wiki_dir: Path | None = None) -> None:
        self.wiki_dir = wiki_dir or settings.wiki_dir
        self.index = self._load_index()
        self.aliases = self._load_aliases()

    def _load_index(self) -> dict[str, str]:
        index_path = self.wiki_dir / "index.md"
        mapping: dict[str, str] = {}
        if not index_path.exists():
            return mapping
        for line in index_path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]\s*->\s*(.+)", line)
            if match:
                entity_id = match.group(1).strip().lower()
                rel = match.group(3).strip().replace("\\", "/")
                if rel.startswith("overlays/"):
                    continue
                mapping[entity_id] = rel
        return mapping

    def _load_aliases(self) -> dict[str, Path]:
        """Map id / filename stem / frontmatter name / aka / slugs -> page path.

        Overlay pages under overlays/ are excluded from global alias resolution.
        """
        aliases: dict[str, Path] = {}
        for path in self.wiki_dir.rglob("*.md"):
            if path.name == "index.md":
                continue
            if is_overlay_path(path, self.wiki_dir):
                continue
            keys = {path.stem.lower(), _slug(path.stem)}
            try:
                post = frontmatter.load(path)
                meta = post.metadata
                eid = str(meta.get("id", "")).strip()
                name = str(meta.get("name", "")).strip()
                page_type = str(meta.get("type", "")).strip().lower()
                if eid:
                    keys.update({eid.lower(), _slug(eid), eid.lower().replace("_", "-")})
                if name:
                    keys.update({name.lower(), _slug(name)})
                    for suffix in (" kingdom", " empire", " village", " theocracy"):
                        if name.lower().endswith(suffix):
                            short = name[: -len(suffix)].strip()
                            keys.update({short.lower(), _slug(short)})
                    # First given name for characters (e.g. "Lizzie Bareare" -> "lizzie")
                    if page_type == "character":
                        first = name.split()[0].strip() if name.split() else ""
                        if first and first.lower() != name.lower():
                            keys.update({first.lower(), _slug(first)})
                aka = meta.get("aka") or meta.get("aliases") or []
                if isinstance(aka, str):
                    aka = [aka]
                for alt in aka:
                    token = str(alt or "").strip()
                    if token:
                        keys.update({token.lower(), _slug(token)})
            except Exception:
                pass
            for key in keys:
                if key and key not in aliases:
                    aliases[key] = path
        for eid, rel in self.index.items():
            path = self.wiki_dir / rel
            if path.exists() and not is_overlay_path(path, self.wiki_dir):
                aliases.setdefault(eid, path)
                aliases.setdefault(_slug(eid), path)
        return aliases

    def resolve_id(self, entity_id: str) -> Path | None:
        key = entity_id.strip().lower()
        if not key:
            return None
        if key in self.aliases:
            return self.aliases[key]
        slug = _slug(entity_id)
        if slug in self.aliases:
            return self.aliases[slug]
        for suffix in (" kingdom", " empire", " village", " theocracy", " forest of tob"):
            if key.endswith(suffix):
                short = key[: -len(suffix)].strip()
                if short in self.aliases:
                    return self.aliases[short]
                if _slug(short) in self.aliases:
                    return self.aliases[_slug(short)]
        if key in self.index:
            path = self.wiki_dir / self.index[key]
            if not is_overlay_path(path, self.wiki_dir):
                return path
        candidates = [
            p
            for p in self.wiki_dir.rglob(f"{key}.md")
            if not is_overlay_path(p, self.wiki_dir)
        ]
        if candidates:
            return candidates[0]
        return None

    def read_page(self, path: Path) -> tuple[dict, str]:
        post = frontmatter.load(path)
        return dict(post.metadata), post.content

    def read_location_meta(self, location_id: str) -> dict:
        """Frontmatter for a location (kind, danger, …). Empty dict if missing."""
        key = (location_id or "").strip()
        if not key:
            return {}
        path = self.resolve_id(key)
        if not path or not path.exists():
            # Prefer locations/ folder even when alias missing.
            candidate = self.wiki_dir / "locations" / f"{key}.md"
            if candidate.exists():
                path = candidate
            else:
                alt = key.replace("_", "-")
                candidate = self.wiki_dir / "locations" / f"{alt}.md"
                if candidate.exists():
                    path = candidate
                else:
                    return {}
        meta, _ = self.read_page(path)
        return dict(meta)

    def load_character(
        self,
        entity_id: str,
        *,
        active_arc_ids: list[str] | None = None,
    ) -> CharacterCard | None:
        path = self.resolve_id(entity_id)
        if not path or not path.exists():
            return None
        meta, body = self.read_page(path)
        arcs = [a for a in (active_arc_ids or []) if a]
        if arcs:
            for stem in resolve_overlay_stems(entity_id, path):
                if any(overlay_path(self.wiki_dir, arc, stem).exists() for arc in arcs):
                    meta, body = merge_character_with_overlays(
                        base_meta=meta,
                        base_body=body,
                        wiki_dir=self.wiki_dir,
                        entity_stem=stem,
                        active_arc_ids=arcs,
                    )
                    break

        raw_type = str(meta.get("type") or "generated")
        card_type = raw_type if raw_type in {"generated", "canonical"} else "canonical"
        raw_tier = str(meta.get("tier") or "minimal")
        tier = raw_tier if raw_tier in {"minimal", "growing", "canonical"} else "minimal"
        return CharacterCard(
            id=meta.get("id", entity_id),
            name=meta.get("name", entity_id),
            tier=tier,  # type: ignore[arg-type]
            type=card_type,  # type: ignore[arg-type]
            role=meta.get("role"),
            location=meta.get("location"),
            template=meta.get("template"),
            faction=meta.get("faction"),
            source=meta.get("source"),
            body=body,
            metadata=dict(meta),
            path=str(path),
        )

    def extract_entities_from_text(self, text: str) -> list[str]:
        found = {token.lower() for token in ENTITY_RE.findall(text)}
        return sorted(found)

    def should_include_adventurer_lore(
        self, *, game_state: GameState, user_message: str
    ) -> bool:
        """True se topic messaggio o presenti suggeriscono lore ranghi/gilda."""
        if _ADVENTURER_TOPIC_RE.search(user_message or ""):
            return True
        for present in game_state.characters_active:
            if _ADVENTURER_PRESENT_RE.search(str(present)):
                return True
        return False

    def should_include_magic_tier_lore(self, *, user_message: str) -> bool:
        """True se il messaggio contiene un cast magia `[...]` (non wiki `[[...]]`)."""
        return bool(_SPELL_CAST_RE.search(user_message or ""))

    def linked_entities(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        _, body = self.read_page(path)
        meta, _ = self.read_page(path)
        combined = body + "\n" + str(meta)
        return [match.lower() for match in WIKI_LINK_RE.findall(combined)]

    def query(
        self,
        *,
        game_state: GameState,
        user_message: str,
        mode: str = "scene",
        character_id: str | None = None,
        cap: int | None = None,
        active_arc_ids: list[str] | None = None,
    ) -> list[tuple[str, dict, str]]:
        cap = cap or settings.wiki_page_cap
        page_ids: list[str] = []

        location = game_state.player.location
        loc_keys: list[str] = []
        if location:
            loc_keys = [location.split("/")[-1], location.replace("/", "_")]
            page_ids.extend(loc_keys)

        # Ibrido B in priorità (prima dei link espansi / present) così non finisce fuori cap
        if mode == "scene" and self.should_include_adventurer_lore(
            game_state=game_state, user_message=user_message
        ):
            page_ids.extend(_ADVENTURER_LORE_IDS)

        if mode == "scene" and self.should_include_magic_tier_lore(
            user_message=user_message
        ):
            page_ids.extend(_MAGIC_TIER_LORE_IDS)

        if loc_keys:
            for key in loc_keys:
                loc_path = self.resolve_id(key)
                if loc_path and loc_path.exists():
                    page_ids.extend(self.linked_entities(loc_path))
                    break

        page_ids.extend(game_state.characters_active)
        if game_state.party_active:
            page_ids.append(game_state.party_active)

        page_ids.extend(self.extract_entities_from_text(user_message))

        if mode == "character" and character_id:
            page_ids = [character_id]

        unique_ids: list[str] = []
        for entity_id in page_ids:
            normalized = entity_id.lower()
            if normalized not in unique_ids:
                unique_ids.append(normalized)

        pages: list[tuple[str, dict, str]] = []
        seen_paths: set[str] = set()
        arcs = [a for a in (active_arc_ids or []) if a]

        for entity_id in unique_ids:
            path = self.resolve_id(entity_id)
            if not path or not path.exists():
                continue
            if str(path) in seen_paths:
                continue
            meta, body = self.read_page(path)
            if arcs and path.parent.name == "characters":
                for stem in resolve_overlay_stems(entity_id, path):
                    if any(overlay_path(self.wiki_dir, arc, stem).exists() for arc in arcs):
                        meta, body = merge_character_with_overlays(
                            base_meta=meta,
                            base_body=body,
                            wiki_dir=self.wiki_dir,
                            entity_stem=stem,
                            active_arc_ids=arcs,
                        )
                        break
            pages.append((entity_id, meta, body))
            seen_paths.add(str(path))
            if len(pages) >= cap:
                break

        return pages
