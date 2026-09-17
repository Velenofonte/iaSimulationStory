import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


LensLevel = Literal["seen", "named"]


class PlayerLens(BaseModel):
    """What the PC has encountered in play (wiki ids → depth).

    - seen: present / visited; describe by role/aspect, no proper name in prose
    - named: name is in play; narrator may use it freely
    """

    entities: dict[str, LensLevel] = Field(default_factory=dict)


class PlayerState(BaseModel):
    id: str = "player"
    name: str = "Avventuriero"
    location: str = "e-rantel"
    party_id: str | None = None
    character_id: str = ""
    origin: Literal["lore", "custom"] = "custom"
    race: str | None = None
    lens: PlayerLens = Field(default_factory=PlayerLens)

    def resolved_character_id(self) -> str:
        if self.character_id.strip():
            return self.character_id.strip()
        return self.name.lower().replace(" ", "-")


class NpcKnowledgeFact(BaseModel):
    """Stable {id, summary} record — NPC knowledge or medium-term situation thread."""

    id: str
    summary: str


def slugify_fact_id(text: str, *, max_len: int = 48) -> str:
    """Deterministic slug from free text (legacy string → id)."""
    raw = (text or "").strip().casefold()
    raw = re.sub(r"[^\w\s-]", " ", raw, flags=re.UNICODE)
    raw = re.sub(r"[\s\-]+", "_", raw).strip("_")
    return raw[:max_len].strip("_") or "thread"


def coerce_fact(item: Any) -> NpcKnowledgeFact | None:
    """Accept NpcKnowledgeFact, {id, summary}, or legacy free-text string."""
    if isinstance(item, NpcKnowledgeFact):
        fid = (item.id or "").strip()
        summary = (item.summary or "").strip()
        if fid and summary:
            return NpcKnowledgeFact(id=fid, summary=summary)
        return None
    if isinstance(item, dict):
        fid = str(item.get("id") or "").strip()
        summary = str(item.get("summary") or item.get("text") or "").strip()
        if summary and not fid:
            fid = slugify_fact_id(summary)
        if fid and summary:
            return NpcKnowledgeFact(id=fid, summary=summary)
        return None
    if isinstance(item, str) and item.strip():
        text = item.strip()
        return NpcKnowledgeFact(id=slugify_fact_id(text), summary=text)
    return None


def coerce_fact_list(v: Any) -> list[NpcKnowledgeFact]:
    """Coerce list of facts; dedupe by id (last wins)."""
    if v is None:
        return []
    if isinstance(v, (str, dict, NpcKnowledgeFact)):
        v = [v]
    if not isinstance(v, list):
        return []
    by_id: dict[str, NpcKnowledgeFact] = {}
    for item in v:
        fact = coerce_fact(item)
        if fact:
            by_id[fact.id] = fact
    return list(by_id.values())


def coerce_id_list(v: Any) -> list[str]:
    """Coerce situations_remove / cleanup: prefer id; accept legacy summary strings."""
    if v is None:
        return []
    if isinstance(v, str):
        v = [v] if v.strip() else []
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for item in v:
        if isinstance(item, dict):
            fid = str(item.get("id") or "").strip()
            if fid:
                out.append(fid)
            elif item.get("summary"):
                out.append(slugify_fact_id(str(item["summary"])))
        elif isinstance(item, NpcKnowledgeFact):
            if item.id.strip():
                out.append(item.id.strip())
        else:
            s = str(item or "").strip()
            if s:
                out.append(s)
    return list(dict.fromkeys(out))


def coerce_npc_knowledge_upsert(v: Any) -> dict[str, list[NpcKnowledgeFact]]:
    """LLM may send {npc_id: [{id, summary}, ...]} or flat / malformed shapes."""
    if v is None or not isinstance(v, dict):
        return {}
    out: dict[str, list[NpcKnowledgeFact]] = {}
    for npc_id, facts in v.items():
        cid = str(npc_id or "").strip()
        if not cid:
            continue
        parsed = coerce_fact_list(facts)
        if parsed:
            out[cid] = parsed
    return out


class OffscreenCharacter(BaseModel):
    """NPC who left the scene but may return (narrative-driven, no TTL)."""

    where: str | None = None
    reason: str | None = None
    from_location: str | None = None


def coerce_present_leave(v: Any) -> dict[str, OffscreenCharacter]:
    """Accept [{"id","where","reason"}], {"id": {...}}, or ["id"]."""
    if v is None:
        return {}
    out: dict[str, OffscreenCharacter] = {}

    def _from_dict(raw: dict[str, Any]) -> OffscreenCharacter:
        where = raw.get("where") or raw.get("location") or raw.get("dove")
        reason = raw.get("reason") or raw.get("perche") or raw.get("why")
        from_loc = raw.get("from_location") or raw.get("from")
        return OffscreenCharacter(
            where=str(where).strip() if where else None,
            reason=str(reason).strip() if reason else None,
            from_location=str(from_loc).strip() if from_loc else None,
        )

    if isinstance(v, dict):
        for key, val in v.items():
            cid = str(key or "").strip()
            if not cid:
                continue
            if isinstance(val, OffscreenCharacter):
                out[cid] = OffscreenCharacter(
                    where=val.where,
                    reason=val.reason,
                    from_location=val.from_location,
                )
            elif isinstance(val, dict):
                # Allow {"id": "milo", "where": "..."} stuffed under a wrong key.
                nested_id = str(val.get("id") or val.get("name") or "").strip()
                if nested_id and nested_id != cid and not any(
                    k in val for k in ("where", "reason", "location", "dove", "from_location", "from")
                ):
                    out[nested_id] = _from_dict(val)
                else:
                    if nested_id:
                        cid = nested_id
                    out[cid] = _from_dict(val)
            elif isinstance(val, str) and val.strip():
                out[cid] = OffscreenCharacter(reason=val.strip())
            else:
                out[cid] = OffscreenCharacter()
        return out

    if isinstance(v, list):
        for item in v:
            if isinstance(item, str):
                cid = item.strip()
                if cid:
                    out[cid] = OffscreenCharacter()
            elif isinstance(item, dict):
                cid = str(item.get("id") or item.get("name") or "").strip()
                if cid:
                    out[cid] = _from_dict(item)
            elif isinstance(item, OffscreenCharacter):
                continue
        return out

    if isinstance(v, str) and v.strip():
        out[v.strip()] = OffscreenCharacter()
        return out

    return out


class CharacterRuntime(BaseModel):
    location: str | None = None
    mood: str | None = None
    relationship: int = 0
    relationship_delta: int = 0
    npc_knowledge: list[NpcKnowledgeFact] = Field(default_factory=list)


class LocationRuntime(BaseModel):
    objects: list[str] = Field(default_factory=list)
    atmosphere: str | None = None
    events: list[str] = Field(default_factory=list)
    ambient: list[str] = Field(
        default_factory=list,
        description="Ruoli anonimi sul luogo (guardia, mercante, …)",
    )


class FrontRuntime(BaseModel):
    id: str
    status: Literal["active", "diverted", "interrupted", "resolved"] = "active"
    cursor_beat: str
    last_fired_beat: str | None = None
    flags: dict[str, bool] = Field(default_factory=dict)
    accumulated_minutes: int = 0
    last_fired_at_day: int | None = None
    last_fired_at_minutes: int | None = None
    distortion_notes: list[str] = Field(default_factory=list)
    interrupted_at_day: int | None = None
    started_day: int | None = None
    # Added to beat.due_abs_minutes when start.relative_to = previous_arc_close
    due_offset_minutes: int = 0


class ChronicleEntry(BaseModel):
    """A world-memory fact with who may know it (reach) and secrecy."""

    id: str
    summary: str
    reach: Literal["none", "local", "regional", "national", "world"] = "local"
    secret: bool = False
    source: Literal["canon_digest", "played_arc", "runtime"] = "runtime"
    arc_id: str | None = None
    day: int | None = None


class ArcRecord(BaseModel):
    """Closed-arc ledger entry (how an arc ended)."""

    arc_id: str
    outcome: Literal["canon", "weak", "diverted", "broken", "lapsed"]
    started_day: int
    closed_day: int
    last_beat: str | None = None
    skipped_beats: list[str] = Field(default_factory=list)
    unresolved_intents: list[str] = Field(default_factory=list)


class WorldPressure(BaseModel):
    """Layer-3 intent left unresolved when an arc closed."""

    id: str
    summary: str
    origin_arc: str
    entities: list[str] = Field(default_factory=list)
    day_opened: int


class StoryRuntime(BaseModel):
    """Era + chronicle + arc chain state for the session."""

    era: str | None = None
    current_arc: str | None = None
    chronicle: list[ChronicleEntry] = Field(default_factory=list)
    arcs: list[ArcRecord] = Field(default_factory=list)
    pressures: list[WorldPressure] = Field(default_factory=list)
    world_flags: dict[str, bool] = Field(default_factory=dict)


class ArcTimelineBeat(BaseModel):
    """Canonical arc beat for UI (not a play log)."""

    id: str
    title: str
    place: str
    status: Literal["done", "current", "upcoming", "skipped"]
    summary: str = ""
    hours_after_previous: float = 0
    estimated_day: int | None = None
    due_time: str | None = None


class ArcTimelineFront(BaseModel):
    id: str
    name: str
    status: str
    cursor_beat: str | None = None
    last_fired_beat: str | None = None
    beats: list[ArcTimelineBeat] = Field(default_factory=list)


class ArcTimelineResponse(BaseModel):
    fronts: list[ArcTimelineFront] = Field(default_factory=list)


class EpisodeRuntime(BaseModel):
    """Ambient episode engine counters (no setting lore)."""

    turn_index: int = 0
    turns_since_event: int = 0
    last_tier: int = 0
    recent_kinds: list[str] = Field(default_factory=list)
    last_beat_turn: int | None = None
    last_stance: str = ""
    consecutive_events: int = 0


class DeedRecord(BaseModel):
    """A notable deed the world may remember (structured; scale id from pack)."""

    id: str
    summary: str
    scale: str = ""
    witnesses: list[str] = Field(default_factory=list)
    attributed: bool = True
    evidence: str = ""
    beneficiary: str = ""
    day: int | None = None
    persistent: bool = False


class NotorietyRuntime(BaseModel):
    """How the world currently reads the player (neutral; no preferred strategy)."""

    score: float = 0.0
    reach: str = "none"
    attribution: dict[str, float] = Field(default_factory=dict)
    labels: list[str] = Field(default_factory=list)
    legend_score: float = 0.0
    deeds: list[DeedRecord] = Field(default_factory=list)


class GameState(BaseModel):
    session_id: str
    story_id: str = "overlord"
    day: int = 1
    minutes: int = 480  # 08:00
    time: str = "Giorno 1 · mattina · 08:00"
    player: PlayerState = Field(default_factory=PlayerState)
    characters_active: list[str] = Field(default_factory=list)
    characters_offscreen: dict[str, OffscreenCharacter] = Field(default_factory=dict)
    characters: dict[str, CharacterRuntime] = Field(default_factory=dict)
    locations: dict[str, LocationRuntime] = Field(default_factory=dict)
    situations: list[NpcKnowledgeFact] = Field(default_factory=list)
    player_findings: list[NpcKnowledgeFact] = Field(
        default_factory=list,
        description="Fatti privati del PG da magie informative (output=info)",
    )
    party_active: str | None = None
    fronts: dict[str, FrontRuntime] = Field(default_factory=dict)
    story: StoryRuntime = Field(default_factory=StoryRuntime)
    episode: EpisodeRuntime = Field(default_factory=EpisodeRuntime)
    notoriety: NotorietyRuntime = Field(default_factory=NotorietyRuntime)
    turns_since_present_review: int = 0
    turns_since_consolidation: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("situations", "player_findings", mode="before")
    @classmethod
    def _coerce_situations(cls, v: Any) -> list[NpcKnowledgeFact]:
        return coerce_fact_list(v)
