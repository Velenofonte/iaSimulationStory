from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.chat import ChatMessage
from app.models.game_state import GameState
from app.models.narrative import (
    NarrativeCanonFacts,
    NarrativeChatTurn,
    NarrativeSpell,
    NarrativeSpellEntry,
    NarrativeTime,
    NarrativeWorldPage,
)
from app.models.reviews import CharacterPresentUpdate, FrontImpact, LocationPresentUpdate


class TurnResolution(BaseModel):
    """Structured turn outcome from the resolver (no prose)."""

    time: NarrativeTime
    location: str | None = None
    present: list[str] | None = None
    spells: list[NarrativeSpell] = Field(default_factory=list)
    scene_brief: list[str] = Field(default_factory=list)
    situations_add: list[str] = Field(default_factory=list)
    situations_remove: list[str] = Field(default_factory=list)

    @field_validator("spells", mode="before")
    @classmethod
    def _coerce_spells(cls, v: object) -> list:
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        out: list = []
        for item in v:
            spell = NarrativeSpell.from_loose(item)
            if spell.name:
                out.append(spell)
        return out

    @field_validator("present", mode="before")
    @classmethod
    def _coerce_present(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, str):
            v = [v] if v.strip() else []
        if not isinstance(v, list):
            return None
        out: list[str] = []
        for item in v:
            if isinstance(item, dict):
                name = item.get("name") or item.get("id") or item.get("role")
                if name:
                    out.append(str(name).strip())
            else:
                s = str(item or "").strip()
                if s:
                    out.append(s)
        return list(dict.fromkeys(out))

    @field_validator("scene_brief", "situations_add", "situations_remove", mode="before")
    @classmethod
    def _coerce_brief(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v] if v.strip() else []
        if not isinstance(v, list):
            return []
        return [str(x).strip() for x in v if str(x or "").strip()]


class SceneStateDelta(BaseModel):
    """Atomic scene mutations. None on replace-fields means no-touch."""

    player_location: str | None = None
    characters_active: list[str] | None = None
    characters_add: list[str] = Field(default_factory=list)
    situations_add: list[str] = Field(default_factory=list)
    situations_remove: list[str] = Field(default_factory=list)
    character_runtime: dict[str, CharacterPresentUpdate] = Field(default_factory=dict)
    location_runtime: dict[str, LocationPresentUpdate] = Field(default_factory=dict)
    front_impacts: list[FrontImpact] = Field(default_factory=list)
    extra_set: dict[str, Any] = Field(default_factory=dict)
    extra_remove: list[str] = Field(default_factory=list)
    party_active: str | None = None
    turns_present_reset: bool = False
    turns_consolidation_reset: bool = False
    preserve_scene_presence: bool = False

    @field_validator(
        "characters_add",
        "situations_add",
        "situations_remove",
        "front_impacts",
        "extra_remove",
        mode="before",
    )
    @classmethod
    def _coerce_none_lists(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("character_runtime", "location_runtime", "extra_set", mode="before")
    @classmethod
    def _coerce_none_dicts(cls, v: Any) -> Any:
        return {} if v is None else v

    @field_validator("characters_active", mode="before")
    @classmethod
    def _coerce_characters_active(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, str):
            v = [v] if v.strip() else []
        if not isinstance(v, list):
            return None
        out: list[str] = []
        for item in v:
            if isinstance(item, dict):
                name = item.get("name") or item.get("id") or item.get("role")
                if name:
                    out.append(str(name).strip())
            else:
                s = str(item or "").strip()
                if s:
                    out.append(s)
        return list(dict.fromkeys(out))


class FrontOutcome(BaseModel):
    """Deterministic front tick side-effects (no direct state writes)."""

    fired_beats: list[str] = Field(default_factory=list)
    situations_add: list[str] = Field(default_factory=list)
    characters_add: list[str] = Field(default_factory=list)
    location_events: dict[str, list[str]] = Field(default_factory=dict)
    location_atmosphere: dict[str, str] = Field(default_factory=dict)
    character_locations: dict[str, str] = Field(default_factory=dict)
    wiki_patches: list[dict[str, Any]] = Field(default_factory=list)
    beat_summaries: list[str] = Field(default_factory=list)
    interrupt_kind: str | None = None
    interrupt_hint: str | None = None

    @field_validator(
        "fired_beats",
        "situations_add",
        "characters_add",
        "wiki_patches",
        "beat_summaries",
        mode="before",
    )
    @classmethod
    def _coerce_none_lists(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("location_events", "location_atmosphere", "character_locations", mode="before")
    @classmethod
    def _coerce_none_dicts(cls, v: Any) -> Any:
        return {} if v is None else v


class NarrativeRenderRequest(BaseModel):
    """Payload for the prose renderer (Pass 2)."""

    canon_facts: NarrativeCanonFacts
    player_action: str
    temporal_context: str = Field(
        default="",
        description="Vincoli dell'epoca corrente; prevalgono sulle biografie future",
    )
    story_context: str = Field(
        default="",
        description="Genere/tono dalla meta della storia; vuoto se assente",
    )
    stance: str = Field(
        default="action",
        description="action|passive|wait — wait = avanza fino alla prima svolta",
    )
    scene_brief: list[str] = Field(default_factory=list)
    interrupt_hint: str | None = None
    fired_beat_summaries: list[str] = Field(default_factory=list)
    character_cards: list[str] = Field(default_factory=list)
    chat_recent: list[NarrativeChatTurn] = Field(default_factory=list)
    spellbook: list[NarrativeSpellEntry] = Field(default_factory=list)
    world_pages: list[NarrativeWorldPage] = Field(
        default_factory=list,
        description="Lore mondo per il cast (es. magic-tier); vuoto se non serve",
    )


class NarrativeRenderResult(BaseModel):
    text: str

    @field_validator("text", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> str:
        return str(v or "").strip()


class CompletedTurn(BaseModel):
    """Accumulated turn artefacts before / after logical commit."""

    state: GameState
    reply: str
    scene_delta: SceneStateDelta | None = None
    front_outcome: FrontOutcome | None = None
    spells: dict[str, str] = Field(default_factory=dict)
    wiki_patches: list[dict[str, Any]] = Field(default_factory=list)
    chat_messages: list[ChatMessage] = Field(default_factory=list)
