"""Per-spell epistemic tags: what the cast produces, how visible it is."""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping, TypedDict

SpellOutput = Literal["info", "effect"]
SpellManifest = Literal["visible", "subtle"]

SPELL_OUTPUTS: frozenset[str] = frozenset({"info", "effect"})
SPELL_MANIFESTS: frozenset[str] = frozenset({"visible", "subtle"})

_TAG_SUFFIX_RE = re.compile(r"\s*\{([^{}]*)\}\s*$")

# Info: detection / divination / sensing (IT primary + EN lore names).
# Do NOT include "invisibil" — Invisibility is an effect others can see happen.
_INFO_RE = re.compile(
    r"(?i)(?:"
    r"rileva|rilevamento|rilevare|"
    r"individua|individuare|"
    r"percepi|percepire|"
    r"scruta|scrutare|"
    r"sonda|sondare|"
    r"identifica|identificare|"
    r"analizza|analizzare|"
    r"esamina|esaminare|"
    r"localizza|localizzare|"
    r"traccia(?:re)?|"
    r"veggenza|chiaroveggenza|divinazione|"
    r"\baura\b|"
    r"leggi\s+la\s+mente|telepat|"
    r"occhio\s+di|vista\s+vera|"
    r"\bdetect\b|\bsense\b|\bscry\b|\bscrying\b|"
    r"\bidentify\b|\blocate\b|"
    r"true\s*sight|clairvoyance|"
    r"\bread\b"
    r")"
)

_SUBTLE_RE = re.compile(
    r"(?i)(?:"
    r"silenzios|"
    r"mentale|"
    r"senza\s+gesti|"
    r"senza\s+parole|"
    r"\boccult(?:o|a|i|e|amente|at[oaie])\b|"
    r"passiv|"
    r"interior"
    r")"
)


class SpellRecord(TypedDict, total=False):
    description: str
    output: SpellOutput
    manifest: SpellManifest


def infer_spell_tags(name: str, description: str = "") -> tuple[SpellOutput, SpellManifest]:
    """Heuristic tags from name + description. Fallback: effect + visible."""
    text = f"{name or ''} {description or ''}".strip()
    output: SpellOutput = "info" if text and _INFO_RE.search(text) else "effect"
    manifest: SpellManifest = "subtle" if text and _SUBTLE_RE.search(text) else "visible"
    return output, manifest


def ensure_spell_tags(
    name: str,
    description: str = "",
    *,
    output: str | None = None,
    manifest: str | None = None,
) -> tuple[SpellOutput, SpellManifest]:
    """Use explicit tags when valid; otherwise infer."""
    out = (output or "").strip().lower()
    man = (manifest or "").strip().lower()
    inferred_out, inferred_man = infer_spell_tags(name, description)
    if out not in SPELL_OUTPUTS:
        out = inferred_out
    if man not in SPELL_MANIFESTS:
        man = inferred_man
    return out, man  # type: ignore[return-value]


def strip_tag_suffix(description: str) -> tuple[str, SpellOutput | None, SpellManifest | None]:
    """Remove trailing ``{info, visible}`` from a description line."""
    raw = (description or "").rstrip()
    match = _TAG_SUFFIX_RE.search(raw)
    if not match:
        return raw, None, None
    tokens = {
        t.strip().lower()
        for t in match.group(1).split(",")
        if t.strip()
    }
    out: SpellOutput | None = None
    man: SpellManifest | None = None
    for tok in tokens:
        if tok in SPELL_OUTPUTS:
            out = tok  # type: ignore[assignment]
        elif tok in SPELL_MANIFESTS:
            man = tok  # type: ignore[assignment]
    clean = raw[: match.start()].rstrip()
    return clean, out, man


def format_tag_suffix(output: SpellOutput, manifest: SpellManifest) -> str:
    return f"{{{output}, {manifest}}}"


def format_spell_line(
    name: str,
    description: str = "",
    *,
    output: SpellOutput = "effect",
    manifest: SpellManifest = "visible",
) -> str:
    """Serialize a spellbook bullet body (without leading ``- ``)."""
    suffix = format_tag_suffix(output, manifest)
    desc = (description or "").strip()
    if desc:
        return f"{name.strip()} — {desc} {suffix}"
    return f"{name.strip()} {suffix}"


def parse_spell_entry_line(line: str) -> dict[str, str]:
    """Parse ``- Name — desc {info, visible}`` (or legacy without braces)."""
    from app.models.narrative import split_spell_line

    raw = (line or "").strip().lstrip("-").strip()
    if not raw:
        return {"name": "", "description": "", "output": "effect", "manifest": "visible"}

    without_tags, parsed_out, parsed_man = strip_tag_suffix(raw)
    name, desc = split_spell_line(without_tags)
    if not name:
        return {"name": "", "description": "", "output": "effect", "manifest": "visible"}
    output, manifest = ensure_spell_tags(
        name, desc, output=parsed_out, manifest=parsed_man
    )
    return {
        "name": name,
        "description": desc,
        "output": output,
        "manifest": manifest,
    }


def coerce_spell_record(
    name: str,
    value: str | Mapping[str, Any] | None,
    *,
    existing: Mapping[str, Any] | None = None,
) -> SpellRecord:
    """Normalize a track_spells value into a SpellRecord."""
    existing = existing or {}
    if isinstance(value, Mapping):
        desc = str(value.get("description") or "").strip()
        out = value.get("output")
        man = value.get("manifest")
    else:
        desc = str(value or "").strip()
        out = None
        man = None
    if not desc:
        desc = str(existing.get("description") or "").strip()
    output, manifest = ensure_spell_tags(
        name,
        desc,
        output=str(out) if out else (existing.get("output") if existing else None),
        manifest=str(man) if man else (existing.get("manifest") if existing else None),
    )
    return SpellRecord(description=desc, output=output, manifest=manifest)
