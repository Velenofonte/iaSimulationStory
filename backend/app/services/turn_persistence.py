from __future__ import annotations

from typing import Any

from app.models import ChatMessage, GameState
from app.services.save_manager import SaveManager
from app.services.wiki_writer import WikiWriter


def commit_turn(
    saves: SaveManager,
    wiki: WikiWriter,
    state: GameState,
    *,
    user_message: str,
    reply: str,
    spells: dict[str, str] | None = None,
    wiki_patches: list[dict[str, Any]] | None = None,
) -> None:
    """Atomic end-of-turn persistence: spells, wiki patches, chat x2, counters, one save."""
    if spells:
        wiki.track_spells(
            state.player.name,
            spells,
            character_id=state.player.resolved_character_id(),
        )
    if wiki_patches:
        wiki.apply_entity_patches(wiki_patches)

    location = state.player.location
    saves.append_chat(
        state.session_id,
        ChatMessage(role="user", content=user_message, location=location),
    )
    saves.append_chat(
        state.session_id,
        ChatMessage(role="assistant", content=reply, location=location),
    )
    state.turns_since_present_review += 1
    state.turns_since_consolidation += 1
    saves.save_game_state(state)
