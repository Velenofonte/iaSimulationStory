"""Normalize character wiki sheet headings to H1-only hybrid contract."""

from __future__ import annotations

import re
import unicodedata

# Promote common nested skill headings to top-level H1.
_SKILL_H2 = re.compile(
    r"^##\s*(Skill\s*/\s*build(?:\s+\[\[.*?\]\].*?|\s+YGGDRASIL)?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ANY_NESTED = re.compile(r"^(#{2,})\s*(.+?)\s*$", re.MULTILINE)

# Sections that belong on overlays / session, strip from seed body if present as H1.
_SEED_FORBIDDEN_H1 = re.compile(
    r"^#\s*(Piani attuali|Current plans?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Sezioni canoniche della scheda (AGENTS.md). DeepSeek spesso le scrive come
# `- **Titolo**:` o `## Titolo` invece di `# Titolo`.
_CANONICAL_SECTION_TITLES: tuple[str, ...] = (
    "Aspetto fisico",
    "Personalita",
    "Personalità",
    "Allineamento",
    "Obiettivo",
    "Obiettivi",
    "Capacita di combattimento",
    "Capacità di combattimento",
    "Skill / build YGGDRASIL",
    "Skill / build",
    "Arti marziali",
    "Ki",
    "Equipaggiamento",
    "Relazioni di potere",
    "Knowledge scope",
    "Relazione col giocatore",
    "Memorie",
    "Open threads",
    "Piani attuali",
)

_LEAKED_FM_LINE = re.compile(
    r"^(id|name|type|tier|role|race|job|location|affiliation|residence|level|source|classes)\s*:\s*.+$",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").casefold().strip()


_CANONICAL_FOLDED = {_fold(t): t for t in _CANONICAL_SECTION_TITLES}


def _canonical_title(raw: str) -> str | None:
    title = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", (raw or "").strip()).strip(" :*-")
    if not title:
        return None
    folded = _fold(title)
    if folded in _CANONICAL_FOLDED:
        canon = _CANONICAL_FOLDED[folded]
        if _fold(canon).startswith("skill"):
            return "Skill / build YGGDRASIL"
        if _fold(canon).startswith("personal"):
            return "Personalita"
        if _fold(canon).startswith("capacita"):
            return "Capacita di combattimento"
        if _fold(canon) == "obiettivi":
            return "Obiettivo"
        return canon
    # Match "Skill / build ..." variants
    if re.match(r"(?i)^skill\s*/\s*build", title):
        return "Skill / build YGGDRASIL"
    return None


def promote_skill_build_headings(body: str) -> str:
    """Turn `## Skill / build ...` into `# Skill / build YGGDRASIL`."""

    def _repl(match: re.Match[str]) -> str:
        return "# Skill / build YGGDRASIL"

    return _SKILL_H2.sub(_repl, body)


def promote_canonical_sections(body: str) -> str:
    """Promote ## / ### / `- **Titolo**:` / `**Titolo**:` canonici a `# Titolo`."""
    lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        promoted: str | None = None

        h_match = re.match(r"^#{2,}\s+(.+?)\s*$", stripped)
        if h_match:
            canon = _canonical_title(h_match.group(1))
            if canon:
                promoted = f"# {canon}"

        if promoted is None:
            bullet = re.match(
                r"^[-*]\s+\*\*(.+?)\*\*\s*:?\s*$",
                stripped,
            ) or re.match(r"^\*\*(.+?)\*\*\s*:?\s*$", stripped)
            if bullet:
                canon = _canonical_title(bullet.group(1))
                if canon:
                    promoted = f"# {canon}"

        lines.append(promoted if promoted is not None else line)
    return "\n".join(lines)


def flatten_nested_headings(body: str) -> str:
    """Convert remaining ##/### headings into bold bullet labels (no nested Hn)."""

    def _repl(match: re.Match[str]) -> str:
        title = match.group(2).strip()
        title = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", title)
        canon = _canonical_title(title)
        if canon:
            return f"# {canon}"
        return f"- **{title}**:"

    return _ANY_NESTED.sub(_repl, body)


def strip_leaked_frontmatter(body: str) -> str:
    """Rimuove chiavi YAML finite per errore nel body (dopo il vero frontmatter)."""
    lines = body.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or _LEAKED_FM_LINE.match(lines[i].strip())):
        i += 1
    return "\n".join(lines[i:]).lstrip("\n")


def strip_name_only_heading(body: str) -> str:
    """Toglie un primo `# Nome` che non e' una sezione canonica."""
    lines = body.splitlines()
    if not lines:
        return body
    first = lines[0].strip()
    m = re.match(r"^#\s+(.+)$", first)
    if not m or m.group(0).startswith("##"):
        return body
    if _canonical_title(m.group(1)):
        return body
    return "\n".join(lines[1:]).lstrip("\n")


def strip_seed_forbidden_sections(body: str) -> str:
    """Remove `# Piani attuali` sections from seed bodies (content until next H1)."""
    lines = body.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if _SEED_FORBIDDEN_H1.match(line.strip()):
            skipping = True
            continue
        if skipping and re.match(r"^#\s+\S", line):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out).strip()


def _clean_h1_titles(body: str) -> str:
    """Strip wiki-link markup from H1 titles; normalize Skill/build title."""
    lines: list[str] = []
    for line in body.splitlines():
        if re.match(r"^#\s+", line) and not re.match(r"^##", line):
            title = line.lstrip("#").strip()
            title = re.sub(
                r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]",
                lambda m: (m.group(2) or m.group(1)).strip(),
                title,
            )
            canon = _canonical_title(title)
            if canon:
                title = canon
            elif re.match(r"(?i)^skill\s*/\s*build", title):
                title = "Skill / build YGGDRASIL"
            elif re.match(r"(?i)^arti marziali", title):
                title = "Arti marziali"
            line = f"# {title}"
        lines.append(line)
    return "\n".join(lines)


def needs_sheet_normalize(body: str) -> bool:
    """True se la scheda sembra malformata per la UI (sezioni bold-bullet / niente H1)."""
    if has_nested_headings(body):
        return True
    if re.search(r"(?m)^[-*]\s+\*\*[^*]+\*\*\s*:?\s*$", body or ""):
        return True
    if not re.search(r"(?m)^#\s+\S", body or ""):
        return True
    return False


def strip_empty_placeholders(body: str) -> str:
    """Pulisce `*(vuoto)*` / `- 0` in Relazione; lascia le sezioni vuote come H1 nudi."""
    lines = body.splitlines()
    out: list[str] = []
    current_h1: str | None = None
    for line in lines:
        h1 = re.match(r"^#\s+(.+)$", line.strip())
        if h1 and not line.strip().startswith("##"):
            current_h1 = _fold(h1.group(1))
            out.append(line)
            continue
        stripped = line.strip()
        # Placeholder LLM
        if re.fullmatch(r"(?:[-*]\s*)?\*+\(?\s*vuoto\s*\)?\*+", stripped, re.IGNORECASE):
            continue
        if re.fullmatch(r"(?:[-*]\s*)?\(vuoto\)", stripped, re.IGNORECASE):
            continue
        if re.fullmatch(r"(?:[-*]\s*)?n/?d\.?", stripped, re.IGNORECASE):
            continue
        # Relazione: "- 0" / "0" → "0"
        if current_h1 and current_h1.startswith("relazione col giocatore"):
            if re.fullmatch(r"[-*]?\s*0\s*", stripped):
                out.append("0")
                continue
        out.append(line)
    return "\n".join(out)


def normalize_character_body(body: str, *, seed: bool = True) -> str:
    """Full post-process for character sheet markdown body."""
    text = body.replace("\r\n", "\n").strip()
    text = strip_leaked_frontmatter(text)
    text = promote_skill_build_headings(text)
    text = promote_canonical_sections(text)
    text = flatten_nested_headings(text)
    text = strip_name_only_heading(text)
    text = _clean_h1_titles(text)
    text = strip_empty_placeholders(text)
    if seed:
        text = strip_seed_forbidden_sections(text)
    # Collapse excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def has_nested_headings(body: str) -> bool:
    return bool(_ANY_NESTED.search(body))
