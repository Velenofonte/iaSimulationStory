"""Load and validate era YAML definitions (entry point + backstory digest)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import settings

REACH_VALUES = frozenset({"none", "local", "regional", "national", "world"})
OUTCOME_VALUES = frozenset({"canon", "weak", "diverted", "broken", "lapsed"})


@dataclass
class EraChronicleLine:
    id: str
    summary: str
    reach: str = "local"
    secret: bool = False
    day_offset: int | None = None


@dataclass
class ArcNextEdge:
    arc: str
    when_outcome: list[str] = field(default_factory=list)
    requires_flags: dict[str, bool] = field(default_factory=dict)


@dataclass
class ArcSequenceNode:
    id: str
    next: list[ArcNextEdge] = field(default_factory=list)


@dataclass
class EraDefinition:
    id: str
    name: str
    canon_source: str
    covers_backstory: str
    start_day: int
    start_minutes: int
    start_location: str
    player_role: str
    overlays_dir: str | None
    insiders: list[str]
    entry_arc: str | None
    arc_sequence: list[ArcSequenceNode]
    arc_by_id: dict[str, ArcSequenceNode]
    world_flags: dict[str, bool]
    chronicle: list[EraChronicleLine]
    raw: dict[str, Any] = field(default_factory=dict)


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()]


def _parse_chronicle(raw_list: Any) -> list[EraChronicleLine]:
    if not isinstance(raw_list, list):
        return []
    seen: set[str] = set()
    out: list[EraChronicleLine] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        if not cid or not summary:
            raise ValueError(f"chronicle entry missing id or summary: {raw!r}")
        if cid in seen:
            raise ValueError(f"duplicate chronicle id: {cid}")
        seen.add(cid)
        reach = str(raw.get("reach") or "local").strip().lower()
        if reach not in REACH_VALUES:
            raise ValueError(f"chronicle {cid}: invalid reach {reach!r}")
        secret = bool(raw.get("secret", False))
        if secret and reach not in {"none", "local"}:
            raise ValueError(
                f"chronicle {cid}: secret entries must have reach none|local, got {reach}"
            )
        day_offset = raw.get("day_offset")
        out.append(
            EraChronicleLine(
                id=cid,
                summary=summary,
                reach=reach,
                secret=secret,
                day_offset=int(day_offset) if day_offset is not None else None,
            )
        )
    return out


def _parse_arc_sequence(raw_list: Any) -> list[ArcSequenceNode]:
    if not isinstance(raw_list, list):
        return []
    nodes: list[ArcSequenceNode] = []
    seen: set[str] = set()
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get("id") or "").strip()
        if not nid:
            raise ValueError("arc_sequence node missing id")
        if nid in seen:
            raise ValueError(f"duplicate arc_sequence id: {nid}")
        seen.add(nid)
        edges: list[ArcNextEdge] = []
        for edge in raw.get("next") or []:
            if not isinstance(edge, dict):
                continue
            target = str(edge.get("arc") or "").strip()
            if not target:
                continue
            outcomes = [
                str(x).strip().lower()
                for x in (edge.get("when_outcome") or [])
                if str(x).strip()
            ]
            for oc in outcomes:
                if oc not in OUTCOME_VALUES:
                    raise ValueError(f"arc {nid} next {target}: invalid outcome {oc!r}")
            flags = {
                str(k): bool(v)
                for k, v in (edge.get("requires_flags") or {}).items()
            }
            edges.append(
                ArcNextEdge(arc=target, when_outcome=outcomes, requires_flags=flags)
            )
        nodes.append(ArcSequenceNode(id=nid, next=edges))
    return nodes


def parse_era_dict(data: dict[str, Any]) -> EraDefinition:
    era_id = str(data.get("id") or "").strip()
    if not era_id:
        raise ValueError("era missing id")
    start = data.get("start") or {}
    if not isinstance(start, dict):
        start = {}
    location = str(start.get("location") or "").strip()
    if not location:
        raise ValueError(f"era {era_id} missing start.location")

    sequence = _parse_arc_sequence(data.get("arc_sequence"))
    arc_by_id = {n.id: n for n in sequence}
    entry_arc = str(data.get("entry_arc") or "").strip() or None
    if entry_arc and entry_arc not in arc_by_id and sequence:
        raise ValueError(f"era {era_id} entry_arc unknown: {entry_arc}")
    for node in sequence:
        for edge in node.next:
            if edge.arc not in arc_by_id:
                raise ValueError(
                    f"era {era_id}: arc_sequence {node.id} next {edge.arc} not defined"
                )

    overlays = data.get("overlays_dir")
    world_flags = {
        str(k): bool(v) for k, v in (data.get("world_flags") or {}).items()
    }
    return EraDefinition(
        id=era_id,
        name=str(data.get("name") or era_id),
        canon_source=str(data.get("canon_source") or "").strip(),
        covers_backstory=str(data.get("covers_backstory") or "").strip(),
        start_day=int(start.get("day") or 1),
        start_minutes=int(start.get("minutes") or 480),
        start_location=location,
        player_role=str(data.get("player_role") or "external").strip(),
        overlays_dir=str(overlays).strip() if overlays else None,
        insiders=_as_str_list(data.get("insiders")),
        entry_arc=entry_arc,
        arc_sequence=sequence,
        arc_by_id=arc_by_id,
        world_flags=world_flags,
        chronicle=_parse_chronicle(data.get("chronicle")),
        raw=data,
    )


def eras_dir(story_id: str) -> Path:
    return settings.story_dir(story_id) / "eras"


class EraLoader:
    def __init__(self, story_id: str | None = None, eras_path: Path | None = None) -> None:
        self.story_id = story_id or settings.default_story_id
        self.eras_path = eras_path or eras_dir(self.story_id)
        self._cache: dict[str, EraDefinition] = {}

    def load(self, era_id: str, *, force: bool = False) -> EraDefinition:
        if not force and era_id in self._cache:
            return self._cache[era_id]
        path = self.eras_path / f"{era_id}.yaml"
        if not path.exists():
            alt = self.eras_path / f"{era_id}.yml"
            if not alt.exists():
                raise FileNotFoundError(f"era not found: {era_id}")
            path = alt
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"invalid era yaml: {path}")
        definition = parse_era_dict(data)
        self._cache[era_id] = definition
        return definition

    def list_ids(self) -> list[str]:
        if not self.eras_path.is_dir():
            return []
        ids: list[str] = []
        for path in sorted(self.eras_path.glob("*.yaml")) + sorted(
            self.eras_path.glob("*.yml")
        ):
            ids.append(path.stem)
        return list(dict.fromkeys(ids))
