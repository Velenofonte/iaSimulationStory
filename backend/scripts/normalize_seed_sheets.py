#!/usr/bin/env python3
"""Mechanically normalize seed character sheets to hybrid H1-only contract."""

from __future__ import annotations

import sys
from pathlib import Path

import frontmatter
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.character_sheet_normalize import normalize_character_body  # noqa: E402


def main() -> None:
    chars = ROOT / "stories" / "overlord" / "wiki" / "characters"
    for path in sorted(chars.glob("*.md")):
        post = frontmatter.load(path)
        body = normalize_character_body(post.content or "", seed=True)
        meta = dict(post.metadata)
        yaml_block = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
        path.write_text(f"---\n{yaml_block}\n---\n\n{body}", encoding="utf-8")
        print(f"normalized {path.name}")


if __name__ == "__main__":
    main()
