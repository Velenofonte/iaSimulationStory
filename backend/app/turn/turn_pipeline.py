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
from app.player.places import infer_location_kind, normalize_place_id, player_at_place
from app.player.presence import normalize_presence_list
from app.story.front_engine import FrontEngine
from app.turn.chat_turn import (
    ChatTurnResult,
    advance_minutes_capped_to_front,
    collect_spells,
    run_scheduled_reviews,
)
from app.turn.game_clock import format_label
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
    state: GameState
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
            state=state,
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
        resolution = self._ensure_distant_engagement_joins(
            resolution,
            message=ctx.message,
            state=ctx.state,
            state_present=list(ctx.present_at_start),
        )
        ctx.resolution = resolution
        return resolution

    def _ensure_distant_engagement_joins(
        self,
        resolution: TurnResolution,
        *,
        message: str,
        state: GameState,
        state_present: list[str],
    ) -> TurnResolution:
        """If the PC engages a distant_cast member, force present_join (UI ↔ dialogue)."""
        distant = self.fronts.distant_cast_entries(state)
        if not distant:
            return resolution

        haystacks = [
            (message or "").casefold(),
            " ".join(resolution.scene_brief or []).casefold(),
        ]
        present_now = {
            str(x).strip().casefold()
            for x in (
                resolution.present
                if resolution.present is not None
                else state_present
            )
            if str(x or "").strip()
        }
        present_now |= {
            str(x).strip().casefold()
            for x in (resolution.present_join or [])
            if str(x or "").strip()
        }
        leave = {
            str(k).strip().casefold()
            for k in (resolution.present_leave or {})
            if str(k or "").strip()
        }

        to_join: list[str] = []
        for entry in distant:
            wid = str(entry.get("id") or "").strip()
            if not wid:
                continue
            key = wid.casefold()
            if key in present_now or key in leave:
                continue
            needles = {key, key.replace("-", " "), key.replace("_", " ")}
            role = str(entry.get("role") or "").strip().casefold()
            if role:
                for part in re.split(r"[/|,]", role):
                    part = part.strip()
                    if len(part) >= 6:
                        needles.add(part)
            try:
                path = self.query.resolve_id(wid)
                if path is not None and path.exists():
                    meta, _ = self.query.read_page(path)
                    name = str(meta.get("name") or "").strip().casefold()
                    if name:
                        needles.add(name)
            except Exception:
                pass
            hit = False
            for hay in haystacks:
                if not hay:
                    continue
                if any(n and n in hay for n in needles):
                    hit = True
                    break
            if hit:
                to_join.append(wid)
                present_now.add(key)

        if not to_join:
            return resolution
        joined = list(dict.fromkeys([*(resolution.present_join or []), *to_join]))
        joined = normalize_presence_list(joined, self.query)
        return resolution.model_copy(update={"present_join": joined})

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
        prev_situation_ids = {str(s.id).strip() for s in state.situations if str(s.id).strip()}
        live_place_before = self.fronts.live_beat_place(state)
        had_live = any(
            bool(rt.live_beat_id)
            for rt in state.fronts.values()
            if rt and rt.status in {"active", "diverted"}
        )
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

        front_outcome = None
        left_live = bool(
            had_live
            and live_place_before
            and not player_at_place(state.player.location, live_place_before)
        )
        if left_live:
            leave_outcome = self.fronts.commit_live_beat(
                state, path="canon", note="left place while live", hydrate_scene=False
            )
            apply_front_outcome(state, leave_outcome)
            front_outcome = leave_outcome

        _suffix, clock_outcome = self._advance_clock(
            state,
            resolution.time.bucket,
            resolution.time.minutes,
            wait_mode=stance == "wait",
            player_action=message,
            stance=stance,
        )
        front_outcome = self._merge_front_outcomes(front_outcome, clock_outcome)

        # Commit after clock so a newly opened live window can close same turn.
        if not left_live:
            now_live = any(
                bool(rt.live_beat_id)
                for rt in state.fronts.values()
                if rt and rt.status in {"active", "diverted"}
            )
            commit_path = self._infer_beat_commit_path(
                resolution, stance=stance, had_live=had_live or now_live
            )
            note = None
            means_inflight = False
            if resolution.beat_commit is not None:
                if resolution.beat_commit.note:
                    note = resolution.beat_commit.note
                means_inflight = bool(resolution.beat_commit.means_inflight)
            engagement = self._live_engagement(
                resolution, stance=stance, message=message
            )
            if now_live:
                allow_land = False
                # Wait on a live beat: the step lands this turn (no micro-telegraph hold).
                if stance == "wait":
                    allow_land = True
                    means_inflight = False
                    if commit_path in {None, "still_live"}:
                        commit_path = "canon"
                commit_path = self.fronts.live_commit_path(
                    state,
                    proposed=commit_path,
                    progress_key=self._live_progress_key(
                        resolution, previous_situation_ids=prev_situation_ids
                    ),
                    hold_reason=note,
                    engagement=engagement,
                    means_inflight=means_inflight,
                    allow_land=allow_land,
                )
            if (
                commit_path in {"canon", "alt", "pillar_failed", "skip"}
                and now_live
            ):
                commit_outcome = self.fronts.commit_live_beat(
                    state, path=commit_path, note=note, hydrate_scene=True
                )
                apply_front_outcome(state, commit_outcome)
                front_outcome = self._merge_front_outcomes(front_outcome, commit_outcome)

        ensure_outcome = self.fronts.ensure_scene_at_player(state)
        if ensure_outcome.beat_summaries or ensure_outcome.live_beats:
            front_outcome = self._merge_front_outcomes(front_outcome, ensure_outcome)

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

    @staticmethod
    def _infer_beat_commit_path(
        resolution: TurnResolution,
        *,
        stance: str,
        had_live: bool,
    ) -> str | None:
        """Resolve beat_commit path; do not force wait→canon while the scene is open."""
        if resolution.beat_commit is not None:
            return resolution.beat_commit.path
        if not had_live:
            return None
        return "still_live"

    @classmethod
    def _live_engagement(
        cls,
        resolution: TurnResolution,
        *,
        stance: str,
        message: str,
    ) -> bool:
        """True when this turn still plays the live beat (PC or cast change)."""
        if resolution.beat_commit and resolution.beat_commit.means_inflight:
            return True
        if resolution.beat_commit and resolution.beat_commit.path == "still_live":
            return True
        if resolution.spells:
            return True
        if resolution.present_join or resolution.present_leave:
            return True
        if resolution.deed is not None:
            return True
        if resolution.player_findings_add:
            return True
        # Soft signal: dialogue / overt action while live (not pure wait).
        if stance == "action":
            return True
        text = (message or "").strip()
        if text and stance != "wait":
            return True
        return False

    # Engine-generated threads: derived from the scene brief / hydrate, so they
    # are not evidence that the player changed anything.
    _DERIVED_SITUATION_PREFIXES = ("brief_", "episode_", "front_")

    @classmethod
    def _live_progress_key(
        cls,
        resolution: TurnResolution,
        *,
        previous_situation_ids: set[str],
    ) -> str:
        """Signature of this turn's new facts; empty string means echo/repetition.

        Only hard signals count: a thread the player opened, information gained,
        the cast changing, a spell, a notable deed. Prose alone (another line of
        dialogue, another threat) is not a fact. Typed interference arrives with
        the review and is tracked on the runtime, so it is not part of the key.
        """
        parts: list[str] = []
        for fact in resolution.situations_add or []:
            fid = str(getattr(fact, "id", "") or "").strip()
            if not fid or fid in previous_situation_ids:
                continue
            if fid.startswith(cls._DERIVED_SITUATION_PREFIXES):
                continue
            parts.append(f"sit:{fid}")
        for fact in resolution.player_findings_add or []:
            fid = str(getattr(fact, "id", "") or "").strip()
            if fid:
                parts.append(f"find:{fid}")
        for cid in resolution.present_join or []:
            parts.append(f"join:{str(cid).strip().casefold()}")
        for cid in (resolution.present_leave or {}):
            parts.append(f"leave:{str(cid).strip().casefold()}")
        for spell in resolution.spells or []:
            name = str(getattr(spell, "name", "") or "").strip().casefold()
            if name:
                parts.append(f"spell:{name}")
        if resolution.deed is not None:
            parts.append(f"deed:{str(getattr(resolution.deed, 'id', '') or '').strip()}")
        return "|".join(sorted(set(parts)))

    @staticmethod
    def _merge_front_outcomes(a: Any, b: Any) -> Any:
        from app.models.turn import FrontOutcome

        if a is None:
            return b
        if b is None:
            return a
        if not isinstance(a, FrontOutcome) or not isinstance(b, FrontOutcome):
            return b or a
        merged = a.model_copy(deep=True)
        merged.fired_beats = list(dict.fromkeys(list(a.fired_beats) + list(b.fired_beats)))
        merged.live_beats = list(dict.fromkeys(list(a.live_beats) + list(b.live_beats)))
        merged.beat_summaries = list(
            dict.fromkeys(list(a.beat_summaries) + list(b.beat_summaries))
        )
        merged.wiki_patches = list(a.wiki_patches) + list(b.wiki_patches)
        merged.characters_add = list(
            dict.fromkeys(list(a.characters_add) + list(b.characters_add))
        )
        merged.situations_add = list(a.situations_add) + list(b.situations_add)
        for cid, loc in b.characters_nearby.items():
            merged.characters_nearby[cid] = loc
        for cid, loc in b.character_locations.items():
            merged.character_locations[cid] = loc
        for loc_id, roles in b.location_ambient.items():
            merged.location_ambient.setdefault(loc_id, [])
            merged.location_ambient[loc_id] = list(
                dict.fromkeys(merged.location_ambient[loc_id] + list(roles))
            )
        for loc_id, events in b.location_events.items():
            merged.location_events.setdefault(loc_id, []).extend(events)
        for loc_id, atm in b.location_atmosphere.items():
            merged.location_atmosphere[loc_id] = atm
        if b.interrupt_hint:
            merged.interrupt_hint = b.interrupt_hint
            merged.interrupt_kind = b.interrupt_kind
        return merged

    def _advance_clock(
        self,
        state: GameState,
        bucket: str | None,
        minutes: int | None,
        *,
        wait_mode: bool = False,
        player_action: str = "",
        stance: str | None = None,
    ):
        # wait_mode kept for call-site compatibility; stance drives the same cap
        # (wait / passive / action all must not overshoot a hydratable beat).
        del wait_mode
        minutes_added = advance_minutes_capped_to_front(
            state,
            self.fronts,
            bucket,
            minutes,
            player_action=player_action,
            stance=stance,
        )
        # Always resolve_tick — even when minutes_added == 0 (beat already due).
        outcome = self.fronts.resolve_tick(state, minutes_added)
        apply_front_outcome(state, outcome)
        return "", outcome
