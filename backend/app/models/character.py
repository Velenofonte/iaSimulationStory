from typing import Any, Literal

from pydantic import BaseModel, Field


class CharacterCard(BaseModel):
    id: str
    name: str = ""
    tier: Literal["minimal", "growing", "canonical"] = "minimal"
    type: Literal["generated", "canonical"] = "generated"
    role: str | None = None
    location: str | None = None
    template: str | None = None
    faction: str | None = None
    source: str | None = None
    body: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    path: str | None = None
