#!/usr/bin/env python3
"""Download raw source pages listed in sources.yaml via MediaWiki API."""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "raw"
SOURCES = ROOT / "sources.yaml"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def wiki_title_from_url(url: str) -> str:
    path = urlparse(url).path
    if "/wiki/" in path:
        return path.split("/wiki/", 1)[1]
    return path.rsplit("/", 1)[-1]


def wikitext_to_plain(wikitext: str) -> str:
    text = wikitext
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)  # simple templates
    text = re.sub(r"\{\|.*?\|\}", "", text, flags=re.S)  # tables
    text = re.sub(r"\[\[File:[^\]]+\]\]", "", text, flags=re.I)
    text = re.sub(r"\[\[Category:[^\]]+\]\]", "", text, flags=re.I)
    text = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", text)  # [[id|label]]
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_via_mediawiki_api(url: str) -> str:
    parsed = urlparse(url)
    title = wiki_title_from_url(url)
    api = f"{parsed.scheme}://{parsed.netloc}/api.php"
    params = {
        "action": "parse",
        "page": title,
        "prop": "wikitext",
        "format": "json",
        "redirects": "1",
    }
    with httpx.Client(headers=BROWSER_HEADERS, timeout=45, follow_redirects=True) as client:
        response = client.get(api, params=params)
        response.raise_for_status()
        data = response.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("info", str(data["error"])))
    wikitext = data.get("parse", {}).get("wikitext", {}).get("*")
    if not wikitext:
        raise RuntimeError(f"No wikitext for title={title}")
    return wikitext_to_plain(wikitext)


def main(force: bool = False, only: str | None = None) -> None:
    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    for group, entries in sources.items():
        for entry in entries:
            if only and only not in entry["out"]:
                continue
            out = RAW_DIR / entry["out"]
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() and not force:
                print(f"skip {out}")
                continue
            print(f"fetch {entry['url']} -> {out}")
            text = fetch_via_mediawiki_api(entry["url"])
            out.write_text(f"# Source: {entry['url']}\n\n{text}", encoding="utf-8")
            time.sleep(0.5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", type=str, default=None, help="Filter outputs containing this substring")
    args = parser.parse_args()
    main(force=args.force, only=args.only)
