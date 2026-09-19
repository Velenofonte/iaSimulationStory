"""One player chat turn: helpers + facade to TurnPipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models import GameState
from app.models.narrative import NarrativeReply, split_spell_line
from app.models.turn import FrontOutcome, TurnResolution
from app.story.front_engine import FrontEngine
from app.turn.game_clock import (
    advance_by_minutes,
    advance_from_parts,
    planned_delta_minutes,
)
from app.turn.state_reducer import apply_front_outcome, apply_scene_delta, resolution_to_delta

if TYPE_CHECKING:
    from app.application.session_context import SessionServices

_BRACKET_SPELL_RE = re.compile(r"\[([^\[\]]+)\]")
_SLEEP_RE = re.compile(
    r"(?i)\b("
    r"dorm(?:o|ire|endo)?|ripos(?:o|are|ando)?|sonno|"
    r"mi\s+stend|stendo|vado\s+a\s+letto|a\s+letto|addorment"
    r")\b"
)


def looks_like_sleep(player_action: str) -> bool:
    return bool(_SLEEP_RE.search(player_action or ""))


def coerce_time_bucket(bucket: str | None, player_action: str) -> str | None:
    """Force riposo when the player clearly goes to sleep/rest until morning."""
    if looks_like_sleep(player_action):
        return "riposo"
    return bucket


@dataclass
class ChatTurnResult:
    reply: str
    state: GameState
    present_review_ran: bool
    consolidation_ran: bool
    input_tokens: int
    input_tokens_system: int
    input_tokens_user: int
    input_tokens_cached: int = 0
    review_tokens: int = 0


def collect_spells(
    user_message: str,
    narr_result: NarrativeReply,
    known: dict[str, dict],
) -> dict[str, dict[str, str]]:
    from app.wiki.spell_tags import coerce_spell_record

    spells: dict[str, dict[str, str]] = {}
    for raw in _BRACKET_SPELL_RE.findall(user_message):
        name, desc = split_spell_line(raw)
        if name and desc:
            existing = known.get(name.lower())
            rec = coerce_spell_record(name, desc, existing=existing)
            # Prefer stored tags for known spells; infer only for brand-new ones.
            spells[name] = {
                "description": rec.get("description") or "",
                "output": (existing or {}).get("output") or rec.get("output") or "effect",
                "manifest": (existing or {}).get("manifest") or rec.get("manifest") or "visible",
            }
    for spell in narr_result.spells:
        name = (spell.name or "").strip()
        desc = (spell.description or "").strip()
        if not name:
            continue
        key = name.lower()
        existing = known.get(key)
        if key not in known or (
            desc and len(desc) > len((existing or {}).get("description") or "")
        ):
            # Do not pass model defaults (effect/visible) as explicit tags — that
            # would clobber UI-edited tags on the next cast of a known spell.
            payload: dict[str, str | None] = {"description": desc}
            raw_out = getattr(spell, "output", None)
            raw_man = getattr(spell, "manifest", None)
            # Only treat as explicit if the LLM/object set non-default intent;
            # when existing tags are present, keep them.
            if existing:
                payload["output"] = existing.get("output")
                payload["manifest"] = existing.get("manifest")
            else:
                if raw_out:
                    payload["output"] = str(raw_out)
                if raw_man:
                    payload["manifest"] = str(raw_man)
            rec = coerce_spell_record(name, payload, existing=existing)
            spells[name] = {
                "description": rec.get("description") or "",
                "output": rec.get("output") or "effect",
                "manifest": rec.get("manifest") or "visible",
            }
    return spells


def apply_narration_to_state(state: GameState, narr_result: NarrativeReply) -> None:
    """Legacy helper — prefer resolution_to_delta + apply_scene_delta."""
    resolution = TurnResolution(
        time=narr_result.time,
        location=narr_result.location,
        present=narr_result.present,
        spells=list(narr_result.spells),
    )
    apply_scene_delta(
        state,
        resolution_to_delta(
            resolution,
            previous_location=state.player.location,
            previous_present=list(state.characters_active),
        ),
    )


def advance_minutes_capped_to_front(
    state: GameState,
    fronts: FrontEngine,
    bucket: str | None,
    minutes: int | None,
    *,
    player_action: str = "",
    stance: str | None = None,
) -> int:
    """Advance the clock without overshooting a hydratable beat at the player's place.

    When ``cap == 0`` (beat already in window), advances 0 minutes so the caller can
    still ``resolve_tick`` and fire in the **same** turn. Wait / observation stances
    use the same cap so a long wait cannot skip past the beat.
    """
    del stance  # same cap for all stances; kept for call-site clarity
    bucket = coerce_time_bucket(bucket, player_action)
    _, planned = planned_delta_minutes(state, bucket, minutes)
    cap = fronts.minutes_to_next_hydratable_beat(state)
    if cap is not None:
        # min(planned, cap) covers overshoot and the already-due (cap=0) case
        return advance_by_minutes(state, min(planned, cap))
    _, minutes_added = advance_from_parts(state, bucket, minutes)
    return minutes_added


def advance_clock_respecting_fronts(
    state: GameState,
    fronts: FrontEngine,
    bucket: str | None,
    minutes: int | None,
    *,
    player_action: str = "",
    stance: str | None = None,
) -> str:
    minutes_added = advance_minutes_capped_to_front(
        state,
        fronts,
        bucket,
        minutes,
        player_action=player_action,
        stance=stance,
    )
    outcome = fronts.resolve_tick(state, minutes_added)
    apply_front_outcome(state, outcome)
    if outcome.wiki_patches:
        fronts.wiki.apply_entity_patches(outcome.wiki_patches)
    return ""


def advance_clock_with_outcome(
    state: GameState,
    fronts: FrontEngine,
    bucket: str | None,
    minutes: int | None,
    *,
    player_action: str = "",
    stance: str | None = None,
) -> tuple[str, FrontOutcome]:
    """Clock advance that returns FrontOutcome without applying wiki patches."""
    minutes_added = advance_minutes_capped_to_front(
        state,
        fronts,
        bucket,
        minutes,
        player_action=player_action,
        stance=stance,
    )
    outcome = fronts.resolve_tick(state, minutes_added)
    apply_front_outcome(state, outcome)
    # Beat entra in prosa via fired_beat_summaries / interrupt_hint del front — niente coda meta.
    return "", outcome


def run_scheduled_reviews(
    svc: SessionServices, state: GameState
) -> tuple[bool, bool, GameState, int]:
    review_tokens = 0
    present_review_ran = False
    if svc.consequences.should_run_present_review(state):
        review = svc.consequences.run_present_review(state)
        present_review_ran = review is not None
        if present_review_ran:
            review_tokens += svc.consequences.last_review_tokens
            state = svc.saves.load_game_state(state.session_id)

    consolidation_ran = False
    if svc.consequences.should_run_consolidation_review(state):
        cons = svc.consequences.run_consolidation_review(state)
        consolidation_ran = cons is not None
        if consolidation_ran:
            review_tokens += svc.consequences.last_review_tokens

    state = svc.saves.load_game_state(state.session_id)
    return present_review_ran, consolidation_ran, state, review_tokens


def process_chat_turn(
    svc: SessionServices, state: GameState, message: str
) -> ChatTurnResult:
    """Delegate to TurnPipeline (resolve → clock/front → render → commit → reviews)."""
    pipeline = getattr(svc, "pipeline", None)
    if pipeline is None:
        raise RuntimeError("SessionServices.pipeline is required")
    return pipeline.run(state, message, svc=svc)
