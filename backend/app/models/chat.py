from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

ActionTag = Literal["dialogue", "overt", "stealth", "hide", "private", "wait", "finding"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    location: str | None = None
    present: list[str] = Field(
        default_factory=list,
        description="characters_active snapshot for this beat (pre-action)",
    )
    tags: list[ActionTag] = Field(
        default_factory=list,
        description="Multi-label action tags (stealth/hide xor overt)",
    )
