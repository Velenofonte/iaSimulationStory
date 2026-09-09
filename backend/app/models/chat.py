from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    location: str | None = None
