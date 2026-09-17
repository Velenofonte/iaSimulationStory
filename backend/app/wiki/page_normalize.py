"""Normalize non-character wiki pages (locations, nations, factions, world)."""

from __future__ import annotations

import re
from typing import Any

import yaml


def flatten_nested_headings(body: str) -> str:
    """Promote ## / ### to # (or bullets if nested under an H1)."""
    lines = body.splitlines()
    out: list[str] = []
    saw_h1 = False
    for line in lines:
        m = re.match(r"^(#{2,6})\s+(.*)$", line)
        if not m:
            out.append(line)
            if line.startswith("# "):
                saw_h1 = True
            continue
        title = m.group(2).strip()
        if not saw_h1:
            out.append(f"# {title}")
            saw_h1 = True
        else:
            # Nested chronology / trivia → bullets under current section
            out.append(f"- {title}")
    return "\n".join(out)


def strip_chronology_sections(body: str) -> str:
    """Remove Chronology / Timeline sections (belong in era chronicle)."""
    parts = re.split(r"(?m)(?=^# )", body)
    kept: list[str] = []
    for part in parts:
        if not part.strip():
            continue
        title_line = part.splitlines()[0] if part.splitlines() else ""
        title = title_line.lstrip("# ").strip().lower()
        if title in {
            "chronology",
            "cronologia",
            "timeline",
            "cronaca",
            "known characters",
            "trivia",
        }:
            continue
        # Drop ### The Xxx Arc leftovers turned into bullets
        cleaned_lines = []
        for line in part.splitlines():
            if re.match(r"^-+\s*the\s+.+\s+arc\s*$", line.strip(), re.I):
                continue
            cleaned_lines.append(line)
        kept.append("\n".join(cleaned_lines))
    return "\n\n".join(kept).strip() + ("\n" if kept else "")


def unwrap_yaml_fence(text: str) -> tuple[dict[str, Any], str]:
    """Extract frontmatter from malformed ```yaml wrappers."""
    meta: dict[str, Any] = {}
    body = text.strip()
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            try:
                loaded = yaml.safe_load(parts[1]) or {}
                if isinstance(loaded, dict):
                    meta = loaded
            except Exception:
                meta = {}
            body = parts[2].strip()
    fence = re.search(r"```yaml\s*\n(.*?)```", body, re.DOTALL | re.IGNORECASE)
    if fence:
        fenced = fence.group(1).strip()
        yaml_text = fenced
        fenced_body = ""
        if "\n---\n" in fenced:
            yaml_text, fenced_body = fenced.split("\n---\n", 1)
        elif yaml_text.startswith("---"):
            bits = yaml_text.split("---", 2)
            if len(bits) >= 3:
                yaml_text, fenced_body = bits[1], bits[2]
        try:
            loaded = yaml.safe_load(yaml_text) or {}
            if isinstance(loaded, dict):
                meta = {**meta, **loaded}
        except Exception:
            pass
        body = body[fence.end() :].strip()
        if fenced_body.strip():
            body = f"{fenced_body.strip()}\n\n{body}".strip() if body else fenced_body.strip()
    body = re.sub(r"\n*```\s*$", "", body).strip()
    return meta, body


def normalize_page_body(
    content: str,
    *,
    page_type: str,
    stem: str,
    defaults: dict[str, Any] | None = None,
) -> str:
    """Normalize location/nation/faction/world page into clean frontmatter + H1 body."""
    meta, body = unwrap_yaml_fence(content)
    defaults = defaults or {}
    body = flatten_nested_headings(body)
    body = strip_chronology_sections(body)
    # Drop empty YAML residue
    body = re.sub(r"^---\s*\n\{\}\s*\n---\s*\n*", "", body).strip()

    meta = {**defaults, **{k: v for k, v in meta.items() if v not in (None, "", {})}}
    meta.setdefault("id", stem.replace("-", "_") if "_" not in stem else stem)
    # Prefer stem-ish ids for locations used by fronts (carne, e-rantel)
    if page_type == "location":
        meta["id"] = defaults.get("id") or stem
    meta.setdefault("name", stem.replace("-", " ").title())
    meta.setdefault("type", page_type)
    meta.setdefault("tier", "canonical" if page_type in {"nation", "faction"} else "minimal")

    if not body.strip():
        body = f"# Descrizione\n{meta['name']}.\n"

    yaml_block = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{yaml_block}\n---\n\n{body.strip()}\n"
