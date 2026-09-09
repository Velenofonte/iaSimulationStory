#!/usr/bin/env python3
"""Transform raw/ pages into stories/<story>/wiki markdown via LLM."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services.character_sheet_normalize import normalize_character_body  # noqa: E402
from app.services.llm_client import LLMClient  # noqa: E402
from app.services.story_catalog import load_story_ingest_prompt  # noqa: E402
from app.services.wiki_overlay import validate_overlay_body  # noqa: E402
from app.services.wiki_writer import WikiWriter  # noqa: E402

CHARACTER_META: dict[str, dict[str, str]] = {
    "ainz": {"id": "ainz_ooal_gown", "name": "Ainz Ooal Gown"},
    "albedo": {"id": "albedo", "name": "Albedo"},
    "demiurge": {"id": "demiurge", "name": "Demiurge"},
    "sebas": {"id": "sebas_tian", "name": "Sebas Tian"},
    "shalltear": {"id": "shalltear_bloodfallen", "name": "Shalltear Bloodfallen"},
    "cocytus": {"id": "cocytus", "name": "Cocytus"},
    "aura": {"id": "aura_bella_fiora", "name": "Aura Bella Fiora"},
    "mare": {"id": "mare_bello_fiore", "name": "Mare Bello Fiore"},
    "enri": {"id": "enri_emmot", "name": "Enri Emmot"},
    "gazef": {"id": "gazef_stronoff", "name": "Gazef Stronoff"},
    "nigun": {"id": "nigun_grid_luin", "name": "Nigun Grid Luin"},
    "nfirea": {"id": "nfirea_bareare", "name": "Nfirea Bareare"},
    # Batch A — Carne / E-Rantel immersion
    "climb": {"id": "climb", "name": "Climb"},
    "brain": {"id": "brain_unglaus", "name": "Brain Unglaus"},
    "clementine": {"id": "clementine", "name": "Clementine"},
    "khajiit": {"id": "khajiit_dale_badantel", "name": "Khajiit Dale Badantel"},
    "momon": {"id": "momon", "name": "Momon"},
    "narberal": {"id": "narberal_gamma", "name": "Narberal Gamma"},
    "lupusregina": {"id": "lupusregina_beta", "name": "Lupusregina Beta"},
    "pandoras-actor": {"id": "pandoras_actor", "name": "Pandora's Actor"},
    "nemu": {"id": "nemu_emmot", "name": "Nemu Emmot"},
    "brita": {"id": "brita", "name": "Brita"},
    "lizzie-bareare": {"id": "lizzie_bareare", "name": "Lizzie Bareare"},
    "hamsuke": {"id": "hamsuke", "name": "Hamsuke"},
    "tuare": {"id": "tuareninya_veyron", "name": "Tuareninya Veyron"},
}


def infer_template(raw_path: Path) -> str:
    parts = raw_path.parts
    if "characters" in parts:
        return str(settings.templates_dir / "character_canonical.md")
    return str(settings.templates_dir / "character_minimal.md")


def normalize_ingest_output(content: str, wiki_path: Path) -> str:
    text = content.strip()
    text = re.sub(r"^---\s*\n\{\}\s*\n---\s*\n+", "", text)

    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3 and parts[1].strip() not in ("", "{}"):
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
    if "```yaml" in body:
        match = re.search(r"```yaml\n(.*?)\n```", body, re.DOTALL)
        if match:
            fenced = match.group(1).strip()
            yaml_text = fenced
            fenced_body = ""
            if "\n---\n" in fenced:
                yaml_text, fenced_body = fenced.split("\n---\n", 1)
                yaml_text = yaml_text.strip()
                fenced_body = fenced_body.strip()
            elif yaml_text.endswith("---"):
                yaml_text = yaml_text[:-3].strip()
            meta = yaml.safe_load(yaml_text) or meta
            body = body[match.end() :].strip()
            if fenced_body:
                body = fenced_body if not body else f"{fenced_body}\n\n{body}"
    body = re.sub(r"\n*```\s*$", "", body).strip()

    stem = wiki_path.stem
    defaults = CHARACTER_META.get(stem, {"id": stem.replace("-", "_"), "name": stem.replace("-", " ").title()})
    if not meta or meta.get("id") in (None, "character_canonical"):
        meta = {**defaults, **{k: v for k, v in meta.items() if k not in ("id", "name") or v not in (None, "character_canonical")}}
    # Known stems always win id/name (avoids Momon page collapsing into Ainz)
    if stem in CHARACTER_META:
        meta["id"] = CHARACTER_META[stem]["id"]
        meta["name"] = CHARACTER_META[stem]["name"]
    else:
        meta.setdefault("id", defaults["id"])
        meta.setdefault("name", defaults["name"])
    if "characters" in wiki_path.parts and "overlays" in wiki_path.parts:
        meta.setdefault("type", "overlay")
        meta.setdefault("arc", wiki_path.parts[wiki_path.parts.index("overlays") + 1] if "overlays" in wiki_path.parts else "")
        meta.setdefault("extends", stem)
    elif "characters" in wiki_path.parts:
        meta.setdefault("type", "character")
        meta.setdefault("tier", "canonical")
    elif wiki_path.parent.name == "world":
        meta.setdefault("type", "world")
        meta.setdefault("tier", "canonical")
    source_match = re.search(r"# Source: (https?://\S+)", content)
    if source_match:
        meta.setdefault("source", source_match.group(1))

    if meta.get("type") == "overlay" or "overlays" in wiki_path.parts:
        errors = validate_overlay_body(body)
        if errors:
            raise ValueError("; ".join(errors))
    elif "characters" in wiki_path.parts:
        body = normalize_character_body(body, seed=True)
        if not body.strip():
            raise ValueError(f"empty character body after normalize for {wiki_path.name}")

    yaml_block = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{yaml_block}\n---\n\n{body}\n"


def main(limit: int | None = None, force: bool = False, only: str | None = None) -> None:
    llm = LLMClient()
    writer = WikiWriter()
    raw_files = sorted(settings.raw_dir.rglob("*.md"))
    if only:
        raw_files = [p for p in raw_files if only in str(p.relative_to(settings.raw_dir)).replace("\\", "/")]
    if limit:
        raw_files = raw_files[:limit]

    system = llm.load_prompt("ingest")
    story_rules = load_story_ingest_prompt(settings.default_story_id)
    if story_rules:
        system = f"{system.rstrip()}\n\n## Regole aggiuntive della storia\n{story_rules}\n"
    for raw_path in raw_files:
        rel = raw_path.relative_to(settings.raw_dir)
        wiki_path = settings.wiki_dir / rel
        if wiki_path.exists() and not force:
            print(f"skip {wiki_path}")
            continue
        template_path = Path(infer_template(raw_path))
        template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
        source = raw_path.read_text(encoding="utf-8")
        user = (
            f"TEMPLATE:\n{template}\n\n"
            f"SOURCE ({raw_path.name}):\n{source[:12000]}\n\n"
            "Genera una pagina wiki completa in markdown con frontmatter YAML."
        )
        content = llm.complete(system=system, user=user, model=settings.llm_model_ingest, temperature=0.3)
        content = normalize_ingest_output(content, wiki_path)
        wiki_path.parent.mkdir(parents=True, exist_ok=True)
        wiki_path.write_text(content.strip() + "\n", encoding="utf-8")
        rel_str = str(rel).replace("\\", "/")
        if not rel_str.startswith("overlays/"):
            writer._add_index(wiki_path.stem, rel_str)
        print(f"ingest {raw_path} -> {wiki_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", type=str, default=None, help="Filter raw paths containing this substring")
    args = parser.parse_args()
    main(limit=args.limit, force=args.force, only=args.only)

    # Post-processing: inject [[links]] between wiki pages
    from scripts.linkify_wiki import process_all as linkify
    print("\n--- linkify wiki ---")
    linkify()
