"""Turn orchestration: named phases for a single player chat turn."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.episodes.episode_director import EpisodeDirector
from app.episodes.episode_pack import load_episode_pack
from app.episodes.notoriety import apply_deed, decay as decay_notoriety
from app.episodes.thread_registry import ensure_exit_threads, ensure_pending_threads
from app.episodes.thread_stall import detect_thread_stall
from app.models import GameState
from app.models.narrative import NarrativeCanonFacts, NarrativeReply, NarrativeRequest
from app.models.turn import NarrativeRenderRequest, TurnResolution
from app.narrative.action_tags import tag_player_action
from app.narrative.narrative_context import NarrativeContextAssembler
from app.narrative.narrative_renderer import NarrativeRenderer
from app.narrative.narrative_stance import (
    compress_repeated_narrative,
    detect_stance,
    last_assistant_message,
    trim_chat_for_passive_render,
)
from app.narrative.turn_resolver import TurnResolver
from app.models.chat import ActionTag
from app.persistence.save_manager import SaveManager
from app.persistence.turn_persistence import commit_turn
from app.player.id_registry import build_known_ids, situation_summaries
from app.player.knowledge import apply_turn_learning
from app.player.places import infer_location_kind, normalize_place_id
from app.player.presence import normalize_presence_list
from app.story.front_engine import FrontEngine
from app.turn.chat_turn import (
    ChatTurnResult,
    coerce_time_bucket,
    collect_spells,
    run_scheduled_reviews,
)
from app.turn.game_clock import (
    advance_by_minutes,
    advance_from_parts,
    format_label,
    planned_delta_minutes,
)
from app.turn.state_reducer import (
    apply_front_outcome,
    apply_scene_delta,
    format_offscreen_lines,
    resolution_to_delta,
)
from app.wiki.wiki_query import WikiQuery
from app.wiki.wiki_writer import WikiWriter

_DIALOGUE_HINT_RE = re.compile(
    r"(?:"
    r'[«"].{2,}[»"]'
    r"|\b(?:dico|chiedo|chiederei)\b"
    r")",
    re.IGNORECASE,
)


@dataclass
class _TurnContext:
    """Scratch state carried across pipeline phases."""

    message: str
    context: NarrativeRequest
    stance: str
    episode: Any
    present_at_start: list[str]
    action_tags: list[ActionTag]
    resolution: TurnResolution | None = None
    spells: dict[str, Any] | None = None
    front_outcome: Any = None
    reply: str = ""


class TurnPipeline:
    def __init__(
        self,
        *,
        assembler: NarrativeContextAssembler,
        resolver: TurnResolver,
        renderer: NarrativeRenderer,
        fronts: FrontEngine,
        wiki: WikiWriter,
        query: WikiQuery,
        saves: SaveManager,
        consequences: object | None = None,
        episodes: EpisodeDirector | None = None,
    ) -> None:
        self.assembler = assembler
        self.resolver = resolver
        self.renderer = renderer
        self.fronts = fronts
        self.wiki = wiki
        self.query = query
        self.saves = saves
        self.consequences = consequences
        self.episodes = episodes or EpisodeDirector()

    def run(self, state: GameState, message: str, *, svc: object | None = None) -> ChatTurnResult:
        sid = state.session_id
        self.saves.write_undo_checkpoint(sid)
        try:
            ctx = self.build_context(state, message)
            self.resolve(ctx)
            self.apply_state(state, ctx)
            self.render(state, ctx)
            self.commit(state, ctx)
            return self.finalize(state, ctx, svc=svc)
        except Exception:
            if self.saves.has_undo_checkpoint(sid):
                try:
                    self.saves.restore_undo_checkpoint(sid)
                except Exception:
                    self.saves.clear_undo_checkpoint(sid)
            raise

    # --- phases -------------------------------------------------------------

    def build_context(self, state: GameState, message: str) -> _TurnContext:
        """Sync scene, assemble narrative request, pick episode + stance."""
        self.fronts.ensure_scene_at_player(state)
        present_at_start = list(state.characters_active)
        context = self.assembler.build_request(state=state, user_message=message)
        stance = context.stance or detect_stance(message)
        action_tags = tag_player_action(message, stance=stance)
        director_stance = stance
        if (
            stance == "action"
            and state.characters_active
            and _DIALOGUE_HINT_RE.search(message or "")
        ):
            director_stance = "dialogue"

        location_meta = self.query.read_location_meta(state.player.location)
        soonest = self.fronts.minutes_to_next_hydratable_beat(state)
        beat_imminent = soonest is not None and soonest <= 0
        episode = self.episodes.decide(
            state,
            stance=director_stance,
            location_meta=location_meta,
            beat_imminent=beat_imminent,
        )
        context.episode = episode
        context.thread_hint = detect_thread_stall(
            list(context.chat_recent),
            message,
            situation_summaries(state),
        )
        return _TurnContext(
            message=message,
            context=context,
            stance=stance,
            episode=episode,
            present_at_start=present_at_start,
            action_tags=action_tags,
        )

    def resolve(self, ctx: _TurnContext) -> TurnResolution:
        """Pass 1 LLM: structured turn resolution + presence normalize."""
        resolution = self.resolver.resolve(ctx.context)

        if resolution.present is not None or resolution.present_join:
            resolution = resolution.model_copy(
                update={
                    "present": (
                        normalize_presence_list(resolution.present, self.query)
                        if resolution.present is not None
                        else None
                    ),
                    "present_join": normalize_presence_list(
                        list(resolution.present_join), self.query
                    ),
                }
            )
        ctx.resolution = resolution
        return resolution

    def apply_state(self, state: GameState, ctx: _TurnContext) -> None:
        """Mutate GameState: scene delta, lens, notoriety, clock, fronts."""
        assert ctx.resolution is not None
        resolution = ctx.resolution
        message = ctx.message
        stance = ctx.stance
        episode = ctx.episode

        known = {
            s["name"].lower(): s
            for s in self.wiki.read_spellbook(
                state.player.name,
                character_id=state.player.resolved_character_id(),
            )
        }
        shim = NarrativeReply(
            text="",
            time=resolution.time,
            spells=list(resolution.spells),
        )
        ctx.spells = collect_spells(message, shim, known)

        prev_location = state.player.location
        prev_present = list(state.characters_active)
        resolution = ensure_pending_threads(resolution, episode, state)
        resolution = ensure_exit_threads(
            resolution,
            player_action=message,
            previous_location=prev_location,
            state=state,
        )
        loc = normalize_place_id(resolution.location) if resolution.location else ""
        prev_norm = normalize_place_id(prev_location or "") or (prev_location or "")
        if loc and loc != prev_norm:
            kind, danger = infer_location_kind(loc)
            try:
                self.wiki.ensure_location(loc, kind=kind, danger=danger)
            except Exception as exc:
                print(f"[turn] ensure_location failed for {loc}: {exc}")
        apply_scene_delta(
            state,
            resolution_to_delta(
                resolution,
                previous_location=prev_location,
                previous_present=prev_present,
                state=state,
                player_action=message,
            ),
        )

        apply_turn_learning(
            state,
            message=message,
            previous_location=prev_location,
            message_entity_ids=self.query.extract_entities_from_text(message),
        )

        if resolution.deed is not None:
            pack = load_episode_pack(state.story_id)
            apply_deed(state, resolution.deed, pack)

        _suffix, front_outcome = self._advance_clock(
            state,
            resolution.time.bucket,
            resolution.time.minutes,
            wait_mode=stance == "wait",
            player_action=message,
        )

        ensure_outcome = self.fronts.ensure_scene_at_player(state)
        if ensure_outcome.beat_summaries:
            if front_outcome is None:
                front_outcome = ensure_outcome
            else:
                front_outcome.beat_summaries = list(
                    dict.fromkeys(
                        list(front_outcome.beat_summaries)
                        + list(ensure_outcome.beat_summaries)
                    )
                )

        apply_turn_learning(
            state,
            message=message,
            previous_location=state.player.location,
            message_entity_ids=self.query.extract_entities_from_text(message),
            front_introduced=list(front_outcome.characters_add) if front_outcome else None,
        )

        if stance == "passive" and len(resolution.scene_brief) > 1:
            resolution = resolution.model_copy(
                update={"scene_brief": resolution.scene_brief[:1]}
            )

        ctx.resolution = resolution
        ctx.front_outcome = front_outcome

    def render(self, state: GameState, ctx: _TurnContext) -> str:
        """Pass 2 LLM: narrative prose (+ anti-repetition)."""
        assert ctx.resolution is not None
        resolution = ctx.resolution
        context = ctx.context
        stance = ctx.stance
        episode = ctx.episode
        front_outcome = ctx.front_outcome
        message = ctx.message

        render_chat = (
            trim_chat_for_passive_render(list(context.chat_recent))
            if stance == "passive"
            else list(context.chat_recent)
        )

        render_world = []
        if self.query.should_include_magic_tier_lore(user_message=message):
            for page in context.world_pages:
                eid = str(page.id).lower().replace("-", "_")
                if eid in {"magic_tier", "tier_magic", "magictier", "tiermagic"} or (
                    "magic" in eid and "tier" in eid
                ):
                    render_world.append(page)

        render_req = NarrativeRenderRequest(
            canon_facts=NarrativeCanonFacts(
                location=state.player.location,
                time=format_label(state.day, state.minutes),
                present=list(state.characters_active),
                offscreen=format_offscreen_lines(
                    state, roles=self.fronts.cast_role_map(state)
                ),
                situations=list(state.situations),
                player_findings=list(state.player_findings),
                known_ids=build_known_ids(state),
                extra=self.assembler.location_scene_extra(state),
            ),
            player_action=message,
            temporal_context=self.fronts.build_temporal_context(state),
            story_context=context.story_context,
            story_so_far=context.story_so_far,
            stance=stance,
            scene_brief=list(resolution.scene_brief),
            player_findings_new=list(resolution.player_findings_add),
            interrupt_hint=front_outcome.interrupt_hint if front_outcome else None,
            fired_beat_summaries=list(front_outcome.beat_summaries) if front_outcome else [],
            character_cards=self.assembler.build_render_cards(state),
            chat_recent=render_chat,
            spellbook=list(context.spellbook),
            world_pages=render_world,
            episode=episode,
            thread_active=bool(context.thread_hint),
            acting_cast=list(state.characters_active),
        )
        reply = self.renderer.render(render_req)
        prior = last_assistant_message(list(context.chat_recent))
        if prior:
            fallback = (
                str(front_outcome.beat_summaries[0])
                if front_outcome and front_outcome.beat_summaries
                else (
                    "Dopo qualche tempo, un nuovo dettaglio modifica la situazione."
                    if stance in {"passive", "wait"}
                    else "La scena avanza di un passo, senza ripetere quanto gia' detto."
                )
            )
            reply = compress_repeated_narrative(reply, prior, fallback=fallback)

        beat_fired = bool(front_outcome and front_outcome.fired_beats)
        EpisodeDirector.record_outcome(
            state, episode, stance=stance, beat_fired=beat_fired
        )
        decay_notoriety(state, days=1.0 / 24.0)
        ctx.reply = reply
        return reply

    def commit(self, state: GameState, ctx: _TurnContext) -> None:
        """Persist chat, wiki patches, spellbook."""
        wiki_patches = list(ctx.front_outcome.wiki_patches) if ctx.front_outcome else []
        has_findings = bool(
            ctx.resolution and ctx.resolution.player_findings_add
        )
        commit_turn(
            self.saves,
            self.wiki,
            state,
            user_message=ctx.message,
            reply=ctx.reply,
            spells=ctx.spells or {},
            wiki_patches=wiki_patches,
            present=ctx.present_at_start,
            tags=ctx.action_tags,
            stance=ctx.stance,
            has_findings=has_findings,
        )

    def finalize(
        self,
        state: GameState,
        ctx: _TurnContext,
        *,
        svc: object | None = None,
    ) -> ChatTurnResult:
        """Scheduled reviews + token accounting."""
        present_review_ran = False
        consolidation_ran = False
        review_tokens = 0
        if svc is not None:
            present_review_ran, consolidation_ran, state, review_tokens = run_scheduled_reviews(
                svc, state  # type: ignore[arg-type]
            )

        r_tot, r_sys, r_usr = self.resolver.last_tokens
        n_tot, n_sys, n_usr = self.renderer.last_tokens
        cached = 0
        usage = self.renderer.llm.last_usage or self.resolver.llm.last_usage
        if usage:
            cached = int(usage.get("cached_tokens") or 0)

        return ChatTurnResult(
            reply=ctx.reply,
            state=state,
            present_review_ran=present_review_ran,
            consolidation_ran=consolidation_ran,
            input_tokens=r_tot + n_tot,
            input_tokens_system=r_sys + n_sys,
            input_tokens_user=r_usr + n_usr,
            input_tokens_cached=cached,
            review_tokens=review_tokens,
        )

    def _advance_clock(
        self,
        state: GameState,
        bucket: str | None,
        minutes: int | None,
        *,
        wait_mode: bool = False,
        player_action: str = "",
    ):
        del wait_mode  # kept for call-site compatibility; no meta interrupt suffix
        bucket = coerce_time_bucket(bucket, player_action)
        _, planned = planned_delta_minutes(state, bucket, minutes)
        cap = self.fronts.minutes_to_next_hydratable_beat(state)
        if cap is not None and planned > cap:
            minutes_added = advance_by_minutes(state, cap)
        else:
            _, minutes_added = advance_from_parts(state, bucket, minutes)

        outcome = self.fronts.resolve_tick(state, minutes_added)
        apply_front_outcome(state, outcome)
        return "", outcome
