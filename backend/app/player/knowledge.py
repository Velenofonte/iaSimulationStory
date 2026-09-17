"""Stable PlayerKnowledge facade — outbound epistemic gate for the PC.

Other domains (front, reducer, wiki, narrative) import from here instead of
reaching into ``player_lens`` internals. Keeps a single contract and avoids
ad-hoc lazy imports scattered across the codebase.
"""

from __future__ import annotations

from typing import Protocol

from app.models.game_state import GameState, LensLevel

from app.player.player_lens import (
    apply_turn_learning,
    backfill_from_chat,
    ensure_lens,
    is_named,
    knows,
    known_ids,
    label,
    learn,
    learn_from_message_tokens,
    level,
    seed_player_lens,
)


class PlayerKnowledge(Protocol):
    """Query/mutate what the player character has learned in play."""

    def level(self, state: GameState, entity_id: str | None) -> LensLevel | None: ...

    def knows(self, state: GameState, entity_id: str | None) -> bool: ...

    def is_named(self, state: GameState, entity_id: str | None) -> bool: ...

    def known_ids(
        self, state: GameState, *, min_level: LensLevel = "seen"
    ) -> list[str]: ...

    def learn(
        self, state: GameState, entity_id: str | None, depth: LensLevel
    ) -> bool: ...

    def label(
        self,
        state: GameState,
        entity_id: str | None,
        role: str | None = None,
    ) -> str: ...


__all__ = [
    "PlayerKnowledge",
    "apply_turn_learning",
    "backfill_from_chat",
    "ensure_lens",
    "is_named",
    "knows",
    "known_ids",
    "label",
    "learn",
    "learn_from_message_tokens",
    "level",
    "seed_player_lens",
]
