from __future__ import annotations

from typing import Any

from app.models import ChatMessage, GameState
from app.models.chat import ActionTag
from app.narrative.action_tags import tag_player_action
from app.persistence.save_manager import SaveManager
from app.wiki.wiki_writer import WikiWriter


def commit_turn(
    saves: SaveManager,
    wiki: WikiWriter,
    state: GameState,
    *,
    user_message: str,
    reply: str,
    spells: dict[str, Any] | None = None,
    wiki_patches: list[dict[str, Any]] | None = None,
    present: list[str] | None = None,
    tags: list[ActionTag] | None = None,
    stance: str | None = None,
    has_findings: bool = False,
) -> None:
    """Atomic end-of-turn persistence: spells, wiki patches, chat x2, counters, one save.

    ``present`` should be characters_active *before* scene mutations (pre-action).
    ``tags`` label the player beat; assistant inherits the same beat tags
    (plus ``finding`` when the turn produced private detection results).
    """
    if spells:
        wiki.track_spells(
            state.player.name,
            spells,
            character_id=state.player.resolved_character_id(),
        )
    if wiki_patches:
        wiki.apply_entity_patches(wiki_patches)

    location = state.player.location
    present_snap = list(present if present is not None else state.characters_active)
    beat_tags = list(tags) if tags is not None else tag_player_action(
        user_message, stance=stance
    )
    assistant_tags = list(beat_tags)
    if has_findings and "finding" not in assistant_tags:
        assistant_tags.append("finding")

    saves.append_chat(
        state.session_id,
        ChatMessage(
            role="user",
            content=user_message,
            location=location,
            present=present_snap,
            tags=beat_tags,
        ),
    )
    saves.append_chat(
        state.session_id,
        ChatMessage(
            role="assistant",
            content=reply,
            location=location,
            present=present_snap,
            tags=assistant_tags,
        ),
    )
    state.turns_since_present_review += 1
    state.turns_since_consolidation += 1
    saves.save_game_state(state)
