from __future__ import annotations

import re

from app.models import GameState
from app.models.narrative import NarrativeCanonFacts, NarrativeReply
from app.models.turn import NarrativeRenderRequest, TurnResolution
from app.services.chat_turn import (
    ChatTurnResult,
    coerce_time_bucket,
    collect_spells,
    run_scheduled_reviews,
)
from app.services.episode_director import EpisodeDirector
from app.services.episode_pack import load_episode_pack
from app.services.front_engine import FrontEngine
from app.services.game_clock import (
    advance_by_minutes,
    advance_from_parts,
    format_label,
    planned_delta_minutes,
)
from app.services.narrative_context import NarrativeContextAssembler
from app.services.narrative_renderer import NarrativeRenderer
from app.services.narrative_stance import (
    compress_repeated_narrative,
    detect_stance,
    last_assistant_message,
    trim_chat_for_passive_render,
)
from app.services.notoriety import apply_deed, decay as decay_notoriety
from app.services.presence import normalize_presence_list
from app.services.places import infer_location_kind, normalize_place_id
from app.services.save_manager import SaveManager
from app.services.state_reducer import (
    apply_front_outcome,
    apply_scene_delta,
    format_offscreen_lines,
    resolution_to_delta,
)
from app.services.turn_persistence import commit_turn
from app.services.thread_registry import ensure_exit_threads, ensure_pending_threads
from app.services.thread_stall import detect_thread_stall
from app.services.id_registry import build_known_ids, situation_summaries
from app.services.turn_resolver import TurnResolver
from app.services.wiki_query import WikiQuery
from app.services.wiki_writer import WikiWriter

_DIALOGUE_HINT_RE = re.compile(
    r"(?:"
    r'[«"].{2,}[»"]'
    r"|\b(?:dico|chiedo|chiederei)\b"
    r")",
    re.IGNORECASE,
)


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
            context = self.assembler.build_request(state=state, user_message=message)
            stance = context.stance or detect_stance(message)
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

            resolution = self.resolver.resolve(context)

            if resolution.present is not None or resolution.present_join:
                resolution = TurnResolution(
                    time=resolution.time,
                    location=resolution.location,
                    present=(
                        normalize_presence_list(resolution.present, self.query)
                        if resolution.present is not None
                        else None
                    ),
                    present_join=normalize_presence_list(
                        list(resolution.present_join), self.query
                    ),
                    present_leave=dict(resolution.present_leave),
                    spells=list(resolution.spells),
                    scene_brief=list(resolution.scene_brief),
                    situations_add=list(resolution.situations_add),
                    situations_remove=list(resolution.situations_remove),
                    npc_knowledge_upsert=dict(resolution.npc_knowledge_upsert),
                    deed=resolution.deed,
                )

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
            spells = collect_spells(message, shim, known)

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
                ),
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

            # passive only: wait must keep full brief (openings / turns).
            if stance == "passive" and len(resolution.scene_brief) > 1:
                resolution = TurnResolution(
                    time=resolution.time,
                    location=resolution.location,
                    present=resolution.present,
                    present_join=list(resolution.present_join),
                    present_leave=dict(resolution.present_leave),
                    spells=list(resolution.spells),
                    scene_brief=resolution.scene_brief[:1],
                    situations_add=list(resolution.situations_add),
                    situations_remove=list(resolution.situations_remove),
                    npc_knowledge_upsert=dict(resolution.npc_knowledge_upsert),
                    deed=resolution.deed,
                )

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
                    offscreen=format_offscreen_lines(state),
                    situations=list(state.situations),
                    known_ids=build_known_ids(state),
                    extra=dict(state.extra),
                ),
                player_action=message,
                temporal_context=self.fronts.build_temporal_context(state),
                story_context=context.story_context,
                stance=stance,
                scene_brief=list(resolution.scene_brief),
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
            # Fractional daily tick each turn so scores don't grow forever.
            decay_notoriety(state, days=1.0 / 24.0)

            wiki_patches = list(front_outcome.wiki_patches) if front_outcome else []
            commit_turn(
                self.saves,
                self.wiki,
                state,
                user_message=message,
                reply=reply,
                spells=spells,
                wiki_patches=wiki_patches,
            )

            present_review_ran = False
            consolidation_ran = False
            review_tokens = 0
            session_svc = svc
            if session_svc is not None:
                present_review_ran, consolidation_ran, state, review_tokens = run_scheduled_reviews(
                    session_svc, state  # type: ignore[arg-type]
                )

            r_tot, r_sys, r_usr = self.resolver.last_tokens
            n_tot, n_sys, n_usr = self.renderer.last_tokens
            cached = 0
            usage = self.renderer.llm.last_usage or self.resolver.llm.last_usage
            if usage:
                cached = int(usage.get("cached_tokens") or 0)

            return ChatTurnResult(
                reply=reply,
                state=state,
                present_review_ran=present_review_ran,
                consolidation_ran=consolidation_ran,
                input_tokens=r_tot + n_tot,
                input_tokens_system=r_sys + n_sys,
                input_tokens_user=r_usr + n_usr,
                input_tokens_cached=cached,
                review_tokens=review_tokens,
            )
        except Exception:
            # Ripristina disco pre-turno (anche scritture incidentali) e consuma lo snapshot.
            if self.saves.has_undo_checkpoint(sid):
                try:
                    self.saves.restore_undo_checkpoint(sid)
                except Exception:
                    self.saves.clear_undo_checkpoint(sid)
            raise

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
        # Nessun suffisso meccanico: il renderer narra i beat da fired_beat_summaries.
        return "", outcome
