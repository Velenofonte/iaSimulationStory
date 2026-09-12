"""Story seeds: meta + wiki paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter
import yaml

from app.config import settings


def list_stories() -> list[dict[str, Any]]:
    root = settings.stories_dir
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        meta_path = path / "meta.yaml"
        if not meta_path.exists():
            continue
        data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        story_id = str(data.get("id") or path.name)
        wiki = path / "wiki"
        items.append(
            {
                "id": story_id,
                "name": str(data.get("name") or story_id),
                "description": str(data.get("description") or ""),
                "start_location": str(data.get("start_location") or "e-rantel"),
                "default_front": data.get("default_front"),
                "has_wiki": wiki.is_dir() and any(wiki.rglob("*.md")),
            }
        )
    return items


def load_story_meta(story_id: str) -> dict[str, Any]:
    path = settings.story_meta_path(story_id)
    if not path.exists():
        raise FileNotFoundError(f"Story not found: {story_id}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid story meta: {story_id}")
    data.setdefault("id", story_id)
    data.setdefault("name", story_id)
    data.setdefault("start_location", "e-rantel")
    return data


def build_story_context(story_id: str) -> str:
    """Genre + narrative_style from story meta for injection into turn payloads."""
    try:
        meta = load_story_meta(story_id)
    except (FileNotFoundError, ValueError):
        return ""
    parts: list[str] = []
    genre = str(meta.get("genre") or "").strip()
    style = str(meta.get("narrative_style") or "").strip()
    if genre:
        parts.append(f"Genere: {genre}")
    if style:
        parts.append(style)
    return "\n".join(parts).strip()


def load_story_ingest_prompt(story_id: str) -> str:
    """Optional story-local ingest rules (stories/<id>/prompts/ingest.md)."""
    path = settings.story_dir(story_id) / "prompts" / "ingest.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_story_episode_prompt(story_id: str) -> str:
    """Optional story-local episode / notoriety rules (stories/<id>/prompts/episode.md)."""
    path = settings.story_dir(story_id) / "prompts" / "episode.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def resolve_seed_wiki(story_id: str) -> Path:
    seed = settings.story_wiki_seed(story_id)
    if not seed.is_dir():
        raise FileNotFoundError(f"Story wiki seed missing: {story_id} ({seed})")
    return seed


def _first_section_summary(body: str, *, max_len: int = 180) -> str:
    text = (body or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    # Skip leading heading, take following non-empty lines
    collected: list[str] = []
    started = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if started and collected:
                break
            started = True
            continue
        if not stripped:
            if collected:
                break
            continue
        collected.append(stripped)
        started = True
        if sum(len(x) for x in collected) >= max_len:
            break
    summary = " ".join(collected).strip()
    if len(summary) > max_len:
        return summary[: max_len - 1].rstrip() + "…"
    return summary


def list_playable_characters(story_id: str) -> list[dict[str, str]]:
    meta = load_story_meta(story_id)
    raw_ids = meta.get("playable_characters") or []
    if not isinstance(raw_ids, list):
        return []
    seed = resolve_seed_wiki(story_id)
    chars_dir = seed / "characters"
    items: list[dict[str, str]] = []
    for entry in raw_ids:
        cid = str(entry).strip()
        if not cid:
            continue
        path = chars_dir / f"{cid}.md"
        if not path.is_file():
            continue
        post = frontmatter.load(path)
        name = str(post.metadata.get("name") or cid)
        items.append(
            {
                "id": cid,
                "name": name,
                "summary": _first_section_summary(post.content),
            }
        )
    return items


def get_playable_character(story_id: str, character_id: str) -> dict[str, Any]:
    """Full seed wiki sheet for a playable character (pre-session preview)."""
    cid = character_id.strip()
    playable_ids = {p["id"] for p in list_playable_characters(story_id)}
    if cid not in playable_ids:
        raise FileNotFoundError(f"Playable character not found: {cid}")
    path = resolve_seed_wiki(story_id) / "characters" / f"{cid}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Playable character not found: {cid}")
    post = frontmatter.load(path)
    spells = _load_seed_spellbook(story_id, cid)
    meta = post.metadata or {}
    job = meta.get("job") or meta.get("classes")
    if isinstance(job, list):
        job = ", ".join(str(x) for x in job)
    return {
        "id": cid,
        "name": str(meta.get("name") or cid),
        "role": meta.get("role"),
        "location": meta.get("location"),
        "race": meta.get("race"),
        "job": job,
        "affiliation": meta.get("affiliation"),
        "residence": meta.get("residence"),
        "level": meta.get("level"),
        "body": (post.content or "").strip(),
        "spells": spells,
    }


def _load_seed_spellbook(story_id: str, character_id: str) -> list[dict[str, str]]:
    path = resolve_seed_wiki(story_id) / "spellbooks" / f"{character_id}.md"
    if not path.is_file():
        return []
    post = frontmatter.load(path)
    lines: list[str] = []
    content = post.content or ""
    in_spellbook = False
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            in_spellbook = "spellbook" in line.lower()
            continue
        if not in_spellbook and not line.startswith("-"):
            continue
        if line.startswith("-"):
            item = line.lstrip("- ").strip()
            if not item:
                continue
            if "—" in item:
                name, desc = item.split("—", 1)
            elif " - " in item:
                name, desc = item.split(" - ", 1)
            else:
                name, desc = item, ""
            name = name.strip()
            if name:
                lines.append({"name": name, "description": desc.strip()})
    return lines


def list_races(story_id: str) -> list[dict[str, str]]:
    meta = load_story_meta(story_id)
    raw = meta.get("races") or []
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for entry in raw:
        if isinstance(entry, str):
            rid = entry.strip()
            if rid:
                items.append({"id": rid, "name": rid.replace("-", " ").title()})
            continue
        if not isinstance(entry, dict):
            continue
        rid = str(entry.get("id") or "").strip()
        if not rid:
            continue
        items.append(
            {
                "id": rid,
                "name": str(entry.get("name") or rid).strip() or rid,
            }
        )
    return items


def list_fronts(story_id: str) -> list[dict[str, str]]:
    seed = resolve_seed_wiki(story_id)
    fronts_dir = seed / "fronts"
    if not fronts_dir.is_dir():
        return []
    items: list[dict[str, str]] = []
    for path in sorted(fronts_dir.glob("*.yaml")) + sorted(fronts_dir.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        fid = str(data.get("id") or path.stem).strip()
        if not fid:
            continue
        items.append(
            {
                "id": fid,
                "name": str(data.get("name") or fid).strip() or fid,
            }
        )
    return items
