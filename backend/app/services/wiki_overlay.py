"""Merge base wiki character pages with arc-specific overlays.

Invariant combat/magic/power sections belong on the base sheet and must not be
moved into arc overlays. Overlays cover era-bound identity: titles, public role,
epoch goals, and temporal knowledge scope.
"""

from __future__ import annotations

import re
from pathlib import Path

import frontmatter

_SECTION_HEADER_RE = re.compile(r"^#\s+(.+?)\s*$")

# Sections that stay on the base sheet (never owned by arc overlays).
INVARIANT_SECTION_KEYS = frozenset(
    {
        "capacita di combattimento",
        "capacità di combattimento",
        "arti marziali",
        "ki",
        "incantesimi noti",
        "incantesimi",
        "relazioni di potere",
        "gerarchia di forza",
        "potere",
    }
)


def normalize_section_key(title: str) -> str:
    """Normalize section titles for overlay replacement (link-aware)."""
    clean = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", title)
    clean = re.sub(r"\[\[([^\]]+)\]\]", r"\1", clean)
    return " ".join(clean.casefold().split())


def split_sections(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (preamble, [(raw_title, section_body), ...])."""
    lines = body.splitlines()
    preamble_lines: list[str] = []
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    buffer: list[str] = []

    for line in lines:
        match = _SECTION_HEADER_RE.match(line)
        if match:
            if current_title is None:
                preamble_lines = buffer
            else:
                sections.append((current_title, "\n".join(buffer).rstrip()))
            current_title = match.group(1).strip()
            buffer = []
        else:
            buffer.append(line)

    if current_title is None:
        return "\n".join(lines).rstrip(), []
    sections.append((current_title, "\n".join(buffer).rstrip()))
    return "\n".join(preamble_lines).rstrip(), sections


def join_sections(preamble: str, sections: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    if preamble.strip():
        parts.append(preamble.strip())
    for title, content in sections:
        block = f"# {title}"
        if content.strip():
            block = f"{block}\n{content.strip()}"
        parts.append(block)
    return "\n\n".join(parts).rstrip() + "\n"


def validate_overlay_body(overlay_body: str) -> list[str]:
    """Return errors if overlay tries to own invariant combat/magic sections."""
    errors: list[str] = []
    _, sections = split_sections(overlay_body)
    for title, _content in sections:
        key = normalize_section_key(title)
        if key in INVARIANT_SECTION_KEYS:
            errors.append(f"overlay must not redefine invariant section: {title}")
    return errors


def merge_section_bodies(base_body: str, overlay_body: str) -> str:
    """Overlay sections replace same-titled base sections; others are appended.

    Invariant combat/magic/power sections in the overlay are ignored.
    """
    preamble, base_sections = split_sections(base_body)
    _, overlay_sections = split_sections(overlay_body)
    if not overlay_sections:
        return base_body if base_body.endswith("\n") else base_body + "\n"

    by_key: dict[str, int] = {}
    merged: list[tuple[str, str]] = []
    for title, content in base_sections:
        key = normalize_section_key(title)
        by_key[key] = len(merged)
        merged.append((title, content))

    for title, content in overlay_sections:
        key = normalize_section_key(title)
        if key in INVARIANT_SECTION_KEYS:
            continue
        if key in by_key:
            idx = by_key[key]
            merged[idx] = (merged[idx][0], content)
        else:
            by_key[key] = len(merged)
            merged.append((title, content))

    return join_sections(preamble, merged)


def merge_frontmatter(base_meta: dict, overlay_meta: dict) -> dict:
    """Overlay metadata overrides selected identity fields; id stays from base."""
    out = dict(base_meta)
    for key in ("name", "role", "location", "faction", "tier", "type"):
        if overlay_meta.get(key) not in (None, ""):
            out[key] = overlay_meta[key]
    arcs = overlay_meta.get("arc")
    if arcs:
        out["arc_overlay"] = arcs
    return out


def overlay_path(wiki_dir: Path, arc_id: str, stem: str) -> Path:
    return wiki_dir / "overlays" / arc_id / "characters" / f"{stem}.md"


def is_overlay_path(path: Path, wiki_dir: Path) -> bool:
    try:
        rel = path.resolve().relative_to(wiki_dir.resolve())
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] == "overlays"


def load_overlay_page(path: Path) -> tuple[dict, str] | None:
    if not path.exists():
        return None
    post = frontmatter.load(path)
    return dict(post.metadata), post.content


def merge_character_with_overlays(
    *,
    base_meta: dict,
    base_body: str,
    wiki_dir: Path,
    entity_stem: str,
    active_arc_ids: list[str],
) -> tuple[dict, str]:
    """Apply overlays for active arcs in order (later arcs override earlier)."""
    meta = dict(base_meta)
    body = base_body
    for arc_id in active_arc_ids:
        if not arc_id:
            continue
        path = overlay_path(wiki_dir, arc_id, entity_stem)
        loaded = load_overlay_page(path)
        if not loaded:
            continue
        o_meta, o_body = loaded
        body = merge_section_bodies(body, o_body)
        meta = merge_frontmatter(meta, o_meta)
    return meta, body


def resolve_overlay_stems(entity_id: str, base_path: Path | None = None) -> list[str]:
    """Candidate filenames for overlay lookup."""
    stems: list[str] = []
    raw = (entity_id or "").strip()
    if raw:
        stems.append(Path(raw).stem)
        stems.append(raw.lower().replace("_", "-"))
        stems.append(raw.lower().replace("-", "_"))
    if base_path is not None:
        stems.append(base_path.stem)
    out: list[str] = []
    for stem in stems:
        key = stem.strip().lower()
        if key and key not in out:
            out.append(key)
    return out
