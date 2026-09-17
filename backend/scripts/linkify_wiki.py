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

# Common English/Italian words that must never become entity aliases.
_STOPLIST = frozenset(
    {
        "great",
        "tomb",
        "dark",
        "king",
        "queen",
        "holy",
        "scripture",
        "sunlight",
        "battle",
        "focus",
        "aura",  # martial-art word; Aura Bella Fiora uses full/short whitelist
        "black",
        "white",
        "blue",
        "red",
        "gold",
        "empire",
        "kingdom",
        "village",
        "forest",
        "plains",
        "guild",
        "order",
        "captain",
        "warrior",
        "magic",
        "caster",
        "sword",
        "light",
        "darkness",
        "overlord",
        "sorcerer",
        "paladin",
        "from",
        "with",
        "that",
        "this",
        "have",
        "been",
        "were",
        "when",
        "where",
        "which",
        "their",
        "there",
        "about",
        "after",
        "before",
        "under",
        "over",
        "into",
        "only",
        "also",
        "than",
        "then",
        "them",
        "they",
        "what",
        "your",
        "will",
        "would",
        "could",
        "should",
        "della",
        "delle",
        "dello",
        "degli",
        "nella",
        "nelle",
        "nello",
        "negli",
        "alla",
        "alle",
        "allo",
        "agli",
        "come",
        "anche",
        "dopo",
        "prima",
        "senza",
        "oltre",
        "verso",
        "presso",
        "contro",
        "durante",
        "mentre",
        "quando",
        "dove",
        "quale",
        "quali",
        "questo",
        "questa",
        "questi",
        "queste",
        "essere",
        "avere",
        "stato",
        "stata",
        "stati",
        "state",
        "ooal",  # never link the middle token of Ainz Ooal Gown alone
        "gown",
    }
)

# Explicit short names allowed as aliases (entity_id -> short forms).
_SHORT_NAME_WHITELIST: dict[str, tuple[str, ...]] = {
    "ainz_ooal_gown": ("ainz",),
    "ainz": ("ainz",),
    "albedo": ("albedo",),
    "demiurge": ("demiurge",),
    "shalltear_bloodfallen": ("shalltear",),
    "shalltear": ("shalltear",),
    "sebas_tian": ("sebas",),
    "sebas": ("sebas",),
    "cocytus": ("cocytus",),
    "aura_bella_fiora": ("aura bella fiora",),  # full only; not bare "aura"
    "mare_bello_fiore": ("mare",),
    "gazef_stronoff": ("gazef",),
    "gazef": ("gazef",),
    "enri_emmot": ("enri",),
    "enri": ("enri",),
    "nfirea_bareare": ("nfirea",),
    "nfirea": ("nfirea",),
    "nigun_grid_luin": ("nigun",),
    "nigun": ("nigun",),
    "momon": ("momon",),
    "narberal_gamma": ("narberal", "nabe"),
    "narberal": ("narberal", "nabe"),
    "climb": ("climb",),
    "brain_unglaus": ("brain",),
    "brain": ("brain",),
    "neia": ("neia",),
    "neia_baraja": ("neia",),
    "remedios": ("remedios",),
    "remedios_custodio": ("remedios",),
    "calca": ("calca",),
    "calca_bessarez": ("calca",),
    "kelart": ("kelart",),
    "kelart_custodio": ("kelart",),
    "jaldabaoth": ("jaldabaoth",),
    "nazarick": ("nazarick",),
    "carne": ("carne",),
    "e-rantel": ("e-rantel", "e rantel"),
    "re-estize": ("re-estize", "re estize"),
    "baharuth": ("baharuth",),
    "roble": ("roble",),
    "hoburns": ("hoburns",),
    "kalinsha": ("kalinsha",),
}


def load_entity_aliases() -> dict[str, str]:
    """Build a map of display_name -> entity_id from base wiki pages (no overlays)."""
    aliases: dict[str, str] = {}
    for md in WIKI_DIR.rglob("*.md"):
        if md.name == "index.md" or is_overlay_path(md, WIKI_DIR):
            continue
        if "spellbooks" in md.parts:
            continue
        try:
            post = frontmatter.load(md)
        except Exception:
            continue
        eid = str(post.metadata.get("id", md.stem))
        name = str(post.metadata.get("name") or "")
        etype = str(post.metadata.get("type") or "")
        if etype == "spellbook":
            continue
        aliases[eid.lower()] = eid
        aliases[md.stem.lower()] = eid
        if name:
            aliases[name.lower()] = eid
        # Whitelisted short forms only (no automatic mono-word splits).
        for short in _SHORT_NAME_WHITELIST.get(eid.lower(), ()):
            key = short.lower().strip()
            if key and key not in _STOPLIST:
                aliases[key] = eid
        for short in _SHORT_NAME_WHITELIST.get(md.stem.lower(), ()):
            key = short.lower().strip()
            if key and key not in _STOPLIST:
                aliases[key] = eid
    # Drop stoplist collisions
    for stop in list(aliases):
        if stop in _STOPLIST:
            del aliases[stop]
    return aliases


_LINK_SPAN_RE = re.compile(r"\[\[[^\]]+\]\]")


def linkify(text: str, aliases: dict[str, str], self_id: str) -> str:
    """Replace plain-text entity names with [[links]], skipping headings and self-refs."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    sorted_names = sorted(aliases.keys(), key=len, reverse=True)
    for line in lines:
        if re.match(r"^#{1,6}\s", line):
            out.append(line)
            continue
        # Mask existing [[...]] spans so we never rewrite inside them.
        placeholders: list[str] = []

        def _mask(m: re.Match) -> str:
            placeholders.append(m.group(0))
            return f"\x00L{len(placeholders) - 1}\x00"

        masked = _LINK_SPAN_RE.sub(_mask, line)
        linked = masked
        for name in sorted_names:
            eid = aliases[name]
            if eid == self_id:
                continue
            pattern = re.compile(
                r"(?<!\w)"
                r"(" + re.escape(name) + r")"
                r"(?!\w)",
                re.IGNORECASE,
            )

            def _replace(m: re.Match, _eid: str = eid) -> str:
                return f"[[{_eid}|{m.group(1)}]]"

            linked = pattern.sub(_replace, linked)
        for i, original in enumerate(placeholders):
            linked = linked.replace(f"\x00L{i}\x00", original)
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
            new_links = linked.count("[[") - original.count("[[")
            print(f"  {md.relative_to(WIKI_DIR)}: +{new_links} links")
        else:
            print(f"  {md.relative_to(WIKI_DIR)}: no changes")


if __name__ == "__main__":
    process_all()
