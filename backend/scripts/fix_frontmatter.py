#!/usr/bin/env python3
"""Fix wiki pages that have a spurious empty frontmatter wrapping the real one."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402

PATTERN = re.compile(
    r"^---\s*\n\{\}\s*\n---\s*\n+"  # empty frontmatter added by frontmatter lib
    r"```yaml\s*\n"  # opening code fence
    r"(---\n.*?\n---)\s*\n"  # real frontmatter (capture)
    r"(.*?)"  # body inside fence (capture)
    r"\n?```\s*$",  # closing code fence
    re.DOTALL | re.MULTILINE,
)


def main(story_id: str | None = None) -> None:
    wiki_dir = settings.story_wiki_seed(story_id or settings.default_story_id)
    if not wiki_dir.is_dir():
        raise SystemExit(f"Wiki seed not found: {wiki_dir}")

    count = 0
    for md in sorted(wiki_dir.rglob("*.md")):
        if md.name == "index.md":
            continue
        text = md.read_text(encoding="utf-8")
        match = PATTERN.match(text)
        if not match:
            continue
        fixed = match.group(1) + "\n" + match.group(2).strip() + "\n"
        md.write_text(fixed, encoding="utf-8")
        count += 1
        print(f"  fixed {md.relative_to(wiki_dir)}")

    print(f"\nFixed {count} files in {wiki_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--story-id", default=None)
    args = parser.parse_args()
    main(story_id=args.story_id)
