"""API request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models import ChatMessage, GameState


class SessionCreateRequest(BaseModel):
    player_name: str = "Avventuriero"
    start_location: str | None = None
    story_id: str = "overlord"
    origin: Literal["lore", "custom"] = "custom"
    character_id: str | None = None
    race: str | None = None
    details: str = ""
    start_mode: Literal["arc", "free", "era"] = "arc"
    front_id: str | None = None
    era_id: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    state: GameState
    messages: list[ChatMessage] = Field(default_factory=list)
    can_undo: bool = False
    undo_count: int = 0


class SpellEntry(BaseModel):
    name: str
    description: str = ""
    output: Literal["info", "effect"] = "effect"
    manifest: Literal["visible", "subtle"] = "visible"


class SpellTagUpdate(BaseModel):
    name: str
    output: Literal["info", "effect"]
    manifest: Literal["visible", "subtle"]


class SpellbookTagsRequest(BaseModel):
    updates: list[SpellTagUpdate] = Field(default_factory=list)


class CharacterSheet(BaseModel):
    id: str
    name: str
    role: str | None = None
    location: str | None = None
    race: str | None = None
    job: str | None = None
    affiliation: str | None = None
    residence: str | None = None
    level: str | int | None = None
    body: str = ""
    spells: list[SpellEntry] = Field(default_factory=list)


class SpellbookResponse(BaseModel):
    player_id: str
    spells: list[SpellEntry] = Field(default_factory=list)


class StorySummary(BaseModel):
    id: str
    name: str
    description: str = ""
    start_location: str = "e-rantel"
    default_front: str | None = None
    has_wiki: bool = False


class PlayableCharacter(BaseModel):
    id: str
    name: str
    summary: str = ""


class RaceOption(BaseModel):
    id: str
    name: str


class FrontOption(BaseModel):
    id: str
    name: str


class EraOption(BaseModel):
    id: str
    name: str
    description: str = ""
    entry_arc: str = ""
    start_location: str = ""


class StoryViewResponse(BaseModel):
    era: str | None = None
    current_arc: str | None = None
    chronicle: list[dict] = Field(default_factory=list)
    arcs: list[dict] = Field(default_factory=list)
    pressures: list[dict] = Field(default_factory=list)
    world_flags: dict[str, bool] = Field(default_factory=dict)
    next_candidates: list[dict] = Field(default_factory=list)


class SessionSummary(BaseModel):
    session_id: str
    story_id: str = "overlord"
    story_name: str = "Overlord"
    player_name: str
    location: str
    time: str
    updated_at: str
    active: bool = False


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    state: GameState
    present_review_ran: bool = False
    consolidation_ran: bool = False
    turns_until_present_review: int = 0
    turns_until_consolidation: int = 0
    input_tokens: int = 0
    input_tokens_system: int = 0
    input_tokens_user: int = 0
    input_tokens_cached: int = 0
    review_tokens: int = 0
    can_undo: bool = False
    undo_count: int = 0


class EndSceneRequest(BaseModel):
    session_id: str


class EndSceneResponse(BaseModel):
    state: GameState
    lint_issues: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    present_review_every_n: int
    consolidate_every_n: int
