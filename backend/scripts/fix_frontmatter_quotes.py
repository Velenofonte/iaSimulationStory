"""Fix wiki pages whose YAML frontmatter breaks on unquoted [[links]]."""

from __future__ import annotations

import sys
from pathlib import Path

import frontmatter
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def fix_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    try:
        frontmatter.load(path)
        return False
    except Exception:
        pass
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    fm_raw = parts[1]
    body = parts[2]
    meta: dict[str, str] = {}
    for line in fm_raw.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip()
    yaml_block = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{yaml_block}\n---{body}", encoding="utf-8")
    frontmatter.load(path)
    return True


def main() -> None:
    roots = [
        ROOT / "stories" / "overlord" / "wiki",
        ROOT / "saves" / "ccbfe9fe-6abb-495d-91e8-7c63bfdb9cd2" / "wiki",
    ]
    fixed: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            try:
                if fix_file(path):
                    fixed.append(str(path.relative_to(ROOT)))
                    print(f"fixed {path.relative_to(ROOT)}")
            except Exception as exc:
                print(f"FAIL {path}: {exc}")
                raise
    print(f"done {len(fixed)}")
    session = ROOT / "saves" / "ccbfe9fe-6abb-495d-91e8-7c63bfdb9cd2" / "wiki"
    for path in session.rglob("*.md"):
        frontmatter.load(path)
    print("session wiki all OK")


if __name__ == "__main__":
    main()
