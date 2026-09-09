import re
from pathlib import Path

from app.config import settings
from app.services.wiki_query import WikiQuery


class WikiLint:
    WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)")

    def __init__(
        self,
        wiki_dir: Path | None = None,
        query: WikiQuery | None = None,
    ) -> None:
        self.wiki_dir = wiki_dir or settings.wiki_dir
        self.query = query or WikiQuery(wiki_dir=self.wiki_dir)

    def run(self) -> list[str]:
        issues: list[str] = []
        for path in self.wiki_dir.rglob("*.md"):
            if path.name == "index.md":
                continue
            text = path.read_text(encoding="utf-8")
            for match in self.WIKI_LINK_RE.findall(text):
                if not self.query.resolve_id(match):
                    issues.append(f"Broken link [[{match}]] in {path.relative_to(self.wiki_dir)}")
        return issues
