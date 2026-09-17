"""Validate era YAML produced by ingest."""

from __future__ import annotations

from typing import Any

from app.story.era_loader import REACH_VALUES, parse_era_dict


def validate_era_yaml(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        era = parse_era_dict(data)
    except ValueError as exc:
        return [str(exc)]
    seen: set[str] = set()
    for line in era.chronicle:
        if line.id in seen:
            errors.append(f"duplicate chronicle id: {line.id}")
        seen.add(line.id)
        if line.reach not in REACH_VALUES:
            errors.append(f"{line.id}: bad reach {line.reach}")
        if line.secret and line.reach not in {"none", "local"}:
            errors.append(f"{line.id}: secret with public reach {line.reach}")
    if not era.start_location:
        errors.append("missing start.location")
    return errors
