"""Validate wiki markdown produced by the ingest pipeline."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import frontmatter

CHARACTER_SECTIONS = (
    "personalita",
    "capacita di combattimento",
    "arti marziali",
    "ki",
    "knowledge scope",
)

WORLD_REQUIRED_KEYS = ("id", "name", "type", "tier")


def fold_section_key(text: str) -> str:
    """Casefold + strip accents for resilient section matching."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.casefold().strip()


def normalize_section_title(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return ""
    title = stripped.lstrip("#").strip()
    title = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", title)
    title = re.sub(r"\[\[([^\]]+)\]\]", r"\1", title)
    return fold_section_key(title)


def section_titles(body: str) -> set[str]:
    titles: set[str] = set()
    for line in body.splitlines():
        title = normalize_section_title(line)
        if title:
            titles.add(title)
    return titles


def parse_wiki_page(text: str) -> tuple[dict[str, Any], str]:
    post = frontmatter.loads(text)
    return dict(post.metadata), post.content


def validate_frontmatter(meta: dict[str, Any], *, expect_type: str | None = None) -> list[str]:
    errors: list[str] = []
    for key in ("id", "name", "type", "tier"):
        if not meta.get(key):
            errors.append(f"missing frontmatter key: {key}")
    if expect_type and meta.get("type") != expect_type:
        errors.append(f"expected type={expect_type}, got {meta.get('type')}")
    if meta == {}:
        errors.append("empty frontmatter")
    return errors


def validate_markdown_structure(text: str) -> list[str]:
    errors: list[str] = []
    if re.search(r"^---\s*\n\{\}\s*\n---", text):
        errors.append("bogus empty frontmatter block")
    if "```yaml" in text:
        errors.append("yaml wrapped in code fence")
    if text.rstrip().endswith("```"):
        errors.append("trailing code fence")
    try:
        meta, body = parse_wiki_page(text)
    except Exception as exc:  # noqa: BLE001
        return [f"frontmatter parse error: {exc}"]
    if not body.strip():
        errors.append("empty body")
    if meta.get("id") == "character_canonical":
        errors.append("generic template id character_canonical")
    return errors


def validate_character_wiki(text: str) -> list[str]:
    errors = validate_markdown_structure(text)
    try:
        meta, body = parse_wiki_page(text)
    except Exception:
        return errors
    errors.extend(validate_frontmatter(meta, expect_type="character"))
    titles = section_titles(body)
    for section in CHARACTER_SECTIONS:
        if section not in titles:
            errors.append(f"missing section: {section}")
    if re.search(r"^#{2,}\s+\S", body, re.MULTILINE):
        errors.append("nested headings (##/###) not allowed on character sheets")
    return errors


def validate_world_wiki(text: str) -> list[str]:
    errors = validate_markdown_structure(text)
    try:
        meta, body = parse_wiki_page(text)
    except Exception:
        return errors
    errors.extend(validate_frontmatter(meta, expect_type="world"))
    if not body.strip():
        errors.append("empty body")
    return errors


def section_body(body: str, section_name: str) -> str:
    target = fold_section_key(section_name)
    lines: list[str] = []
    in_section = False
    for line in body.splitlines():
        title = normalize_section_title(line)
        if title:
            if title == target:
                in_section = True
                continue
            if in_section:
                break
        elif in_section:
            lines.append(line)
    return "\n".join(lines).strip()
