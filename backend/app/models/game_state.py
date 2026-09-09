from typing import Any, Literal

from pydantic import BaseModel, Field


class PlayerState(BaseModel):
    id: str = "player"
    name: str = "Avventuriero"
    location: str = "e-rantel"
    party_id: str | None = None
    character_id: str = ""
    origin: Literal["lore", "custom"] = "custom"
    race: str | None = None

    def resolved_character_id(self) -> str:
        if self.character_id.strip():
            return self.character_id.strip()
        return self.name.lower().replace(" ", "-")


class CharacterRuntime(BaseModel):
    location: str | None = None
    mood: str | None = None
    relationship: int = 0
    relationship_delta: int = 0


class LocationRuntime(BaseModel):
    objects: list[str] = Field(default_factory=list)
    atmosphere: str | None = None
    events: list[str] = Field(default_factory=list)


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


class GameState(BaseModel):
    session_id: str
    story_id: str = "overlord"
    day: int = 1
    minutes: int = 480  # 08:00
    time: str = "Giorno 1 · mattina · 08:00"
    player: PlayerState = Field(default_factory=PlayerState)
    characters_active: list[str] = Field(default_factory=list)
    characters: dict[str, CharacterRuntime] = Field(default_factory=dict)
    locations: dict[str, LocationRuntime] = Field(default_factory=dict)
    situations: list[str] = Field(default_factory=list)
    party_active: str | None = None
    fronts: dict[str, FrontRuntime] = Field(default_factory=dict)
    turns_since_present_review: int = 0
    turns_since_consolidation: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)
