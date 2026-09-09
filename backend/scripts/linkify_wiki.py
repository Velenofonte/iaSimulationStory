#!/usr/bin/env python3
"""Post-process wiki pages: inject [[links]] where entity names appear as plain text."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import frontmatter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services.wiki_overlay import is_overlay_path  # noqa: E402

WIKI_DIR = settings.wiki_dir


def load_entity_aliases() -> dict[str, str]:
    """Build a map of display_name -> entity_id from base wiki pages (no overlays)."""
    aliases: dict[str, str] = {}
    for md in WIKI_DIR.rglob("*.md"):
        if md.name == "index.md" or is_overlay_path(md, WIKI_DIR):
            continue
        # Spellbooks are not narrative entities — linking "Ainz" to spellbook ids breaks sheets
        if "spellbooks" in md.parts:
            continue
        try:
            post = frontmatter.load(md)
        except Exception:
            continue
        eid = post.metadata.get("id", md.stem)
        name = post.metadata.get("name", "")
        etype = str(post.metadata.get("type") or "")
        if etype == "spellbook":
            continue
        # id itself
        aliases[str(eid).lower()] = eid
        # display name
        if name:
            aliases[name.lower()] = eid
        # common short names from id (e.g. "shalltear_bloodfallen" -> "Shalltear")
        for part in str(name).split():
            if len(part) >= 4:
                aliases[part.lower()] = eid
    return aliases


def linkify(text: str, aliases: dict[str, str], self_id: str) -> str:
    """Replace plain-text entity names with [[links]], skipping headings and self-refs."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    sorted_names = sorted(aliases.keys(), key=len, reverse=True)
    for line in lines:
        # Never rewrite markdown headings (UI splits on `# ` titles)
        if re.match(r"^#{1,6}\s", line):
            out.append(line)
            continue
        linked = line
        for name in sorted_names:
            eid = aliases[name]
            if eid == self_id:
                continue
            pattern = re.compile(
                r"(?<!\[\[)"
                r"(?<!\w)"
                r"(" + re.escape(name) + r")"
                r"(?!\w)"
                r"(?![^\[]*\]\])",
                re.IGNORECASE,
            )

            def _replace(m: re.Match, _eid: str = eid) -> str:
                return f"[[{_eid}|{m.group(1)}]]"

            linked = pattern.sub(_replace, linked)
        out.append(linked)
    return "".join(out)


def process_all() -> None:
    aliases = load_entity_aliases()
    print(f"Loaded {len(aliases)} aliases from wiki pages")
    for md in sorted(WIKI_DIR.rglob("*.md")):
        if md.name == "index.md":
            continue
        try:
            post = frontmatter.load(md)
        except Exception:
            continue
        self_id = post.metadata.get("id", md.stem)
        original = post.content
        linked = linkify(original, aliases, self_id)
        if linked != original:
            post.content = linked
            md.write_text(frontmatter.dumps(post), encoding="utf-8")
            # Count new links
            new_links = linked.count("[[") - original.count("[[")
            print(f"  {md.relative_to(WIKI_DIR)}: +{new_links} links")
        else:
            print(f"  {md.relative_to(WIKI_DIR)}: no changes")


if __name__ == "__main__":
    process_all()
