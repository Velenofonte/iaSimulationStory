"""Load and validate arc front YAML definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import settings


@dataclass
class FrontBeat:
    id: str
    title: str
    place: str
    hours_after_previous: float
    intents: list[str]
    prereq_all: list[str]
    prereq_none: list[str]
    cast_in_world: list[str]
    scene_canon: str
    wiki_writes: list[dict[str, Any]]
    set_flags: list[str]
    clear_flags: list[str]
    prompt_inject: str = ""
    resolves_arc: str | None = None
    due_abs_minutes: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FrontCastMember:
    key: str
    wiki: str | None
    role: str
    appear_from: str
    default_location: str | None


@dataclass
class FrontVariant:
    id: str
    replaces: list[str]
    when_flag: str
    when_equals: bool
    effect: str
    note: str = ""


@dataclass
class FrontDefinition:
    id: str
    name: str
    start_beat: str
    start_day: int
    start_minutes: int
    flags_initial: dict[str, bool]
    beats: list[FrontBeat]
    beat_by_id: dict[str, FrontBeat]
    cast: dict[str, FrontCastMember]
    variants: list[FrontVariant]
    intents_layer2: list[dict[str, Any]]
    intents_layer3: list[dict[str, Any]]
    prompt_policy: dict[str, Any]
    temporal_constraints: list[str]


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def _parse_marks(on_fire: dict[str, Any]) -> tuple[list[str], list[str]]:
    set_flags = _as_str_list(on_fire.get("set_flags"))
    clear_flags = _as_str_list(on_fire.get("clear_flags"))
    for mark in _as_str_list(on_fire.get("marks")):
        if mark.endswith("_false"):
            clear_flags.append(mark[: -len("_false")])
        else:
            set_flags.append(mark)
    # de-dupe preserving order
    set_flags = list(dict.fromkeys(set_flags))
    clear_flags = list(dict.fromkeys(clear_flags))
    return set_flags, clear_flags


def _parse_beat(raw: dict[str, Any]) -> FrontBeat:
    beat_id = str(raw.get("id") or "").strip()
    if not beat_id:
        raise ValueError("beat missing id")
    place = str(raw.get("place") or "").strip()
    if not place:
        raise ValueError(f"beat {beat_id} missing place")
    prereq = raw.get("prereq") or {}
    if not isinstance(prereq, dict):
        prereq = {}
    on_fire = raw.get("on_fire") or {}
    if not isinstance(on_fire, dict):
        on_fire = {}
    set_flags, clear_flags = _parse_marks(on_fire)
    wiki_writes = on_fire.get("wiki_writes") or []
    if not isinstance(wiki_writes, list):
        wiki_writes = []
    return FrontBeat(
        id=beat_id,
        title=str(raw.get("title") or beat_id),
        place=place,
        hours_after_previous=float(raw.get("hours_after_previous") or 0),
        intents=_as_str_list(raw.get("intents")),
        prereq_all=_as_str_list(prereq.get("all")),
        prereq_none=_as_str_list(prereq.get("none")),
        cast_in_world=_as_str_list(raw.get("cast_in_world")),
        scene_canon=str(raw.get("scene_canon") or "").strip(),
        wiki_writes=wiki_writes,
        set_flags=set_flags,
        clear_flags=clear_flags,
        prompt_inject=str(raw.get("prompt_inject") or "").strip(),
        resolves_arc=raw.get("resolves_arc"),
        raw=raw,
    )


def parse_front_dict(data: dict[str, Any]) -> FrontDefinition:
    front_id = str(data.get("id") or "").strip()
    if not front_id:
        raise ValueError("front missing id")
    raw_beats = data.get("beats")
    if not isinstance(raw_beats, list) or not raw_beats:
        raise ValueError(f"front {front_id} missing beats")
    beats = [_parse_beat(b) for b in raw_beats if isinstance(b, dict)]
    beat_by_id = {b.id: b for b in beats}
    start = data.get("start") or {}
    start_beat = str(start.get("beat") or beats[0].id)
    if start_beat not in beat_by_id:
        raise ValueError(f"front {front_id} start beat unknown: {start_beat}")

    cast: dict[str, FrontCastMember] = {}
    for key, raw in (data.get("cast") or {}).items():
        if not isinstance(raw, dict):
            continue
        wiki = raw.get("wiki")
        cast[str(key)] = FrontCastMember(
            key=str(key),
            wiki=str(wiki) if wiki else None,
            role=str(raw.get("role") or ""),
            appear_from=str(raw.get("appear_from") or start_beat),
            default_location=(
                str(raw["default_location"]) if raw.get("default_location") is not None else None
            ),
        )

    variants: list[FrontVariant] = []
    for raw in data.get("variants") or []:
        if not isinstance(raw, dict):
            continue
        when = raw.get("when") or {}
        variants.append(
            FrontVariant(
                id=str(raw.get("id") or ""),
                replaces=_as_str_list(raw.get("replaces")),
                when_flag=str(when.get("flag") or ""),
                when_equals=bool(when.get("equals", True)),
                effect=str(raw.get("effect") or "interrupt_default_queue"),
                note=str(raw.get("note") or "").strip(),
            )
        )

    flags_initial = {
        str(k): bool(v) for k, v in (data.get("flags_initial") or {}).items()
    }
    start_day = int(start.get("day") or 1)
    start_minutes = int(start.get("minutes") or 480)
    # Absolute due: start clock + cumulative hours_after_previous
    cum = start_day * 1440 + (start_minutes % 1440)
    for beat in beats:
        cum += int(beat.hours_after_previous * 60)
        beat.due_abs_minutes = cum

    temporal = _as_str_list(data.get("temporal_constraints"))
    overlays = data.get("overlays") or {}
    if isinstance(overlays, dict):
        temporal = list(dict.fromkeys(temporal + _as_str_list(overlays.get("notes"))))

    return FrontDefinition(
        id=front_id,
        name=str(data.get("name") or front_id),
        start_beat=start_beat,
        start_day=start_day,
        start_minutes=start_minutes,
        flags_initial=flags_initial,
        beats=beats,
        beat_by_id=beat_by_id,
        cast=cast,
        variants=variants,
        intents_layer2=list(data.get("intents_layer2") or []),
        intents_layer3=list(data.get("intents_layer3") or []),
        prompt_policy=dict(data.get("prompt_policy") or {}),
        temporal_constraints=temporal,
    )


class FrontLoader:
    def __init__(self, fronts_dir: Path | None = None) -> None:
        self.fronts_dir = fronts_dir or settings.fronts_dir
        self._cache: dict[str, FrontDefinition] = {}

    def load(self, front_id: str, *, force: bool = False) -> FrontDefinition:
        if not force and front_id in self._cache:
            return self._cache[front_id]
        path = self.fronts_dir / f"{front_id}.yaml"
        if not path.exists():
            alt = self.fronts_dir / f"{front_id}.yml"
            if not alt.exists():
                raise FileNotFoundError(f"front not found: {front_id}")
            path = alt
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"invalid front yaml: {path}")
        definition = parse_front_dict(data)
        if definition.id != front_id and definition.id.replace("-", "_") != front_id.replace("-", "_"):
            # allow filename stem as load key even if id matches closely
            pass
        self._cache[front_id] = definition
        return definition
