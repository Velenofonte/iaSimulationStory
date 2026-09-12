"""Build the known_ids registry shown to the resolver LLM."""

from __future__ import annotations

from typing import Any

from app.models.game_state import GameState, NpcKnowledgeFact

# Cap facts per NPC in the prompt payload (most recent kept).
_NPC_FACT_CAP = 8


def _fact_dict(fact: NpcKnowledgeFact) -> dict[str, str]:
    return {"id": fact.id, "summary": fact.summary}


def build_known_ids(state: GameState) -> dict[str, Any]:
    """Registry of reusable ids: situations + all NPCs with knowledge.

    Offscreen / inactive NPCs are included so the model can reuse their ids
    when the player returns to them (e.g. guild clerk).
    """
    situations = [_fact_dict(s) for s in state.situations if s.id and s.summary]
    npc_knowledge: dict[str, list[dict[str, str]]] = {}
    for cid, runtime in state.characters.items():
        facts = list(runtime.npc_knowledge or [])
        if not facts:
            continue
        # Prefer most recent entries when over cap.
        trimmed = facts[-_NPC_FACT_CAP:] if len(facts) > _NPC_FACT_CAP else facts
        npc_knowledge[cid] = [_fact_dict(f) for f in trimmed if f.id and f.summary]
    return {
        "situations": situations,
        "npc_knowledge": npc_knowledge,
    }


def situation_summaries(state: GameState) -> list[str]:
    """Human-readable situation lines (UI / legacy string consumers)."""
    return [s.summary for s in state.situations if (s.summary or "").strip()]
