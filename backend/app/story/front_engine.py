"""Arc front engine: tick timeline beats against game clock."""

from __future__ import annotations

from typing import Any

from app.models import (
    ArcTimelineBeat,
    ArcTimelineFront,
    ArcTimelineResponse,
    FrontRuntime,
    GameState,
)
from app.models.game_state import NpcKnowledgeFact, coerce_fact_list, slugify_fact_id
from app.models.reviews import FrontImpact
from app.models.turn import FrontOutcome
from app.story.front_loader import FrontBeat, FrontDefinition, FrontLoader
from app.turn.game_clock import sync_time_label
from app.player.knowledge import is_named, knows, label
from app.player.places import player_at_place
from app.turn.state_reducer import apply_front_outcome
from app.wiki.wiki_writer import WikiWriter


def format_due_day(day: int) -> str:
    """Beat windows are day-level for UI/prompt; hour is narrator's choice."""
    return f"Giorno {max(0, int(day))}"


def absolute_minutes(day: int, minutes: int) -> int:
    return max(0, int(day)) * 1440 + max(0, int(minutes) % 1440)


def _dedupe_facts(facts: list[NpcKnowledgeFact]) -> list[NpcKnowledgeFact]:
    by_id: dict[str, NpcKnowledgeFact] = {}
    for fact in coerce_fact_list(facts):
        by_id[fact.id] = fact
    return list(by_id.values())


def day_minutes_from_abs(abs_minutes: int) -> tuple[int, int]:
    abs_m = max(0, int(abs_minutes))
    return abs_m // 1440, abs_m % 1440


def scene_canon_to_bullets(scene_canon: str, limit: int = 3) -> list[str]:
    lines = []
    for raw in (scene_canon or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("(") and line.endswith(")"):
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


class FrontEngine:
    def __init__(
        self,
        loader: FrontLoader | None = None,
        wiki: WikiWriter | None = None,
        story: Any = None,
    ) -> None:
        self.loader = loader or FrontLoader()
        self.wiki = wiki or WikiWriter()
        self.story = story

    def activate(
        self,
        state: GameState,
        front_id: str,
        *,
        fire_start: bool = True,
        reset_clock: bool = True,
        relative_to_now: bool = False,
    ) -> FrontRuntime:
        definition = self.loader.load(front_id)
        due_offset = 0
        if relative_to_now or definition.start_relative_to == "previous_arc_close":
            base = absolute_minutes(state.day, state.minutes)
            start_abs = absolute_minutes(definition.start_day, definition.start_minutes)
            due_offset = max(0, base - start_abs)
        runtime = FrontRuntime(
            id=definition.id,
            status="active",
            cursor_beat=definition.start_beat,
            flags=dict(definition.flags_initial),
            accumulated_minutes=0,
            started_day=state.day,
            due_offset_minutes=due_offset,
        )
        state.fronts[definition.id] = runtime
        if reset_clock:
            state.day = definition.start_day
            state.minutes = definition.start_minutes
            sync_time_label(state)
        if fire_start:
            # hours_after_previous == 0 → fire immediately
            self.tick(state, 0, front_ids=[definition.id])
        return runtime

    def _beat_due(self, runtime: FrontRuntime, beat: FrontBeat) -> int:
        return int(beat.due_abs_minutes) + int(runtime.due_offset_minutes or 0)

    def seed_world_after_arc(self, state: GameState, front_id: str) -> FrontRuntime:
        """Apply an arc's default beat queue off-screen, then leave it resolved.

        Used for free-world start after a chosen arc: wiki_writes land on the
        session wiki, clock jumps past the last beat, no active beat scripting
        and no era overlays (resolved fronts are not in _active_arc_ids).
        """
        saved_location = state.player.location
        saved_situations = list(state.situations)
        saved_characters = list(state.characters_active)

        runtime = self.activate(state, front_id, fire_start=False)
        definition = self.loader.load(front_id)
        max_due = max(
            (self._beat_due(runtime, b) for b in definition.beats),
            default=0,
        )
        state.day, state.minutes = day_minutes_from_abs(max_due)
        sync_time_label(state)
        # Off-camera seed: never open a live window — fire the default queue.
        self.tick(
            state,
            0,
            front_ids=[definition.id],
            hydrate_scene=False,
            allow_live=False,
        )

        runtime = state.fronts[definition.id]
        if runtime.status in {"active", "diverted"}:
            runtime.status = "resolved"
        if self.story is not None:
            self.story.on_arc_closed(state, definition.id)

        # Free play: keep the create-session location/scene, not beat hydrates.
        state.player.location = saved_location
        state.situations = saved_situations
        state.characters_active = saved_characters
        return runtime

    def resolve_tick(
        self,
        state: GameState,
        delta_minutes: int = 0,
        *,
        front_ids: list[str] | None = None,
        hydrate_scene: bool = True,
        defer_presence: bool = False,
        allow_live: bool = True,
    ) -> FrontOutcome:
        """Advance front runtime; return scene/wiki side-effects without applying them.

        Mutates front cursors/flags/status only. Does not touch situations,
        characters_active, locations, or wiki files.

        ``allow_live=False`` forces off-camera fire even if the PG is on the beat
        place (used by ``seed_world_after_arc``).
        """
        del delta_minutes  # clock is advanced by caller; gate is absolute due
        outcome = FrontOutcome()
        ids = front_ids or list(state.fronts.keys())
        now_abs = absolute_minutes(state.day, state.minutes)
        closed_fronts: list[str] = []
        for front_id in ids:
            runtime = state.fronts.get(front_id)
            if not runtime or runtime.status not in {"active", "diverted"}:
                continue
            definition = self.loader.load(front_id)
            while True:
                beat = definition.beat_by_id.get(runtime.cursor_beat)
                if not beat:
                    runtime.status = "resolved"
                    closed_fronts.append(front_id)
                    break
                if now_abs < self._beat_due(runtime, beat):
                    break

                variant = self._matching_variant(definition, runtime, beat.id)
                if variant and variant.effect == "interrupt_default_queue":
                    runtime.status = "interrupted"
                    runtime.interrupted_at_day = state.day
                    if variant.note:
                        runtime.distortion_notes.append(variant.note.splitlines()[0])
                    outcome.interrupt_kind = "interrupt_default_queue"
                    outcome.interrupt_hint = (
                        variant.note.splitlines()[0] if variant.note else None
                    )
                    closed_fronts.append(front_id)
                    break
                if variant and variant.effect == "divert":
                    runtime.status = "diverted"
                    if variant.note:
                        runtime.distortion_notes.append(variant.note.splitlines()[0])
                    if not self._advance_cursor(definition, runtime):
                        break
                    continue

                if not self._prereq_ok(runtime.flags, beat):
                    runtime.status = "interrupted"
                    runtime.interrupted_at_day = state.day
                    closed_fronts.append(front_id)
                    break

                if defer_presence and player_at_place(state.player.location, beat.place):
                    break

                # Already live at this cursor: stay until commit (do not re-fire).
                # Whether the window survives another turn is decided by the turn
                # content (see ``live_commit_path``), not by a timer here.
                if runtime.live_beat_id == beat.id:
                    if allow_live and player_at_place(state.player.location, beat.place):
                        outcome.live_beats.append(beat.id)
                        break
                    # Left the place while live — commit off-camera below via explicit call;
                    # if we reach here without prior leave commit, fire off-site now.
                    self._clear_live(runtime)

                on_site = player_at_place(state.player.location, beat.place)
                is_start_immediate = (
                    runtime.last_fired_beat is None
                    and float(beat.hours_after_previous or 0) == 0
                    and beat.id == definition.start_beat
                )
                if (
                    allow_live
                    and on_site
                    and not defer_presence
                    and not is_start_immediate
                ):
                    # Enter live participation window: pressure on-site, no commit yet.
                    self._enter_live(state, runtime, beat, outcome, now_abs=now_abs)
                    break

                fire_data = self._fire_collect(
                    state,
                    definition,
                    runtime,
                    beat,
                    hydrate_scene=hydrate_scene,
                )
                self._merge_fire_into_outcome(outcome, fire_data, beat_id=beat.id)
                self._clear_live(runtime)

                if beat.resolves_arc:
                    runtime.status = "resolved"
                    closed_fronts.append(front_id)
                    break
                if not self._advance_cursor(definition, runtime):
                    runtime.status = "resolved"
                    closed_fronts.append(front_id)
                    break
            # Telemetry: minutes past last due (or start)
            if runtime.last_fired_beat:
                last = definition.beat_by_id.get(runtime.last_fired_beat)
                marker = self._beat_due(runtime, last) if last else now_abs
            else:
                marker = absolute_minutes(definition.start_day, definition.start_minutes) + int(
                    runtime.due_offset_minutes or 0
                )
            runtime.accumulated_minutes = max(0, now_abs - marker)

        # de-dupe lists while preserving order
        outcome.situations_add = _dedupe_facts(list(outcome.situations_add))
        outcome.characters_add = list(dict.fromkeys(outcome.characters_add))
        outcome.beat_summaries = list(dict.fromkeys(outcome.beat_summaries))
        for loc_id, events in list(outcome.location_events.items()):
            outcome.location_events[loc_id] = list(dict.fromkeys(events))

        # Notify story engine of terminal transitions (idempotent)
        if self.story is not None:
            for fid in list(dict.fromkeys(closed_fronts)):
                runtime = state.fronts.get(fid)
                if runtime and runtime.status in {
                    "resolved",
                    "interrupted",
                }:
                    # interrupted closes only via stall unless resolves; still record broken on interrupt? Plan says on_arc_closed at terminal. For interrupted we wait for stall unless we want immediate broken record.
                    if runtime.status == "resolved":
                        self.story.on_arc_closed(state, fid)
            self.story.check_stall(state)
        return outcome

    def tick(
        self,
        state: GameState,
        delta_minutes: int = 0,
        *,
        front_ids: list[str] | None = None,
        hydrate_scene: bool = True,
        defer_presence: bool = False,
        allow_live: bool = True,
    ) -> list[str]:
        """Backward-compatible tick: resolve, apply scene hydrate, write wiki."""
        outcome = self.resolve_tick(
            state,
            delta_minutes,
            front_ids=front_ids,
            hydrate_scene=hydrate_scene,
            defer_presence=defer_presence,
            allow_live=allow_live,
        )
        apply_front_outcome(state, outcome)
        if outcome.wiki_patches:
            self.wiki.apply_entity_patches(outcome.wiki_patches)
        return list(outcome.fired_beats)

    def sync_to_clock(self, state: GameState, *, for_display: bool = False) -> list[str]:
        """Catch up fronts to the game clock.

        for_display (GET timeline): defer presence fires; no scene hydrate.
        """
        return self.tick(
            state,
            0,
            hydrate_scene=not for_display,
            defer_presence=for_display,
        )

    def minutes_to_next_hydratable_beat(self, state: GameState) -> int | None:
        """Minutes until the next beat that would hydrate at the player's place.

        When a beat is already ``live`` on-site, returns None so the clock can
        advance scene minutes without capping to a fire (commit is separate).
        """
        if self._any_live_on_site(state):
            return None
        info = self.next_hydratable_beat_at_player(state)
        return None if info is None else int(info["due_in_minutes"])

    def next_hydratable_beat_at_player(self, state: GameState) -> dict[str, Any] | None:
        """Soonest pending beat at the player's place (due_in_minutes + scene bullets)."""
        soonest: dict[str, Any] | None = None
        now_abs = absolute_minutes(state.day, state.minutes)
        for front_id, runtime in state.fronts.items():
            if not runtime or runtime.status not in {"active", "diverted"}:
                continue
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            cursor = runtime.cursor_beat
            flags = dict(runtime.flags)
            for _ in range(len(definition.beats) + 2):
                beat = definition.beat_by_id.get(cursor)
                if not beat:
                    break

                variant = None
                saved_flags = runtime.flags
                runtime.flags = flags
                try:
                    variant = self._matching_variant(definition, runtime, beat.id)
                finally:
                    runtime.flags = saved_flags

                if variant and variant.effect == "interrupt_default_queue":
                    break
                if variant and variant.effect == "divert":
                    idx = next(
                        (i for i, b in enumerate(definition.beats) if b.id == cursor),
                        -1,
                    )
                    if idx < 0 or idx + 1 >= len(definition.beats):
                        break
                    cursor = definition.beats[idx + 1].id
                    continue

                if not self._prereq_ok(flags, beat):
                    break

                if player_at_place(state.player.location, beat.place):
                    wait = max(0, self._beat_due(runtime, beat) - now_abs)
                    candidate = {
                        "id": beat.id,
                        "title": beat.title or beat.id,
                        "place": beat.place,
                        "due_in_minutes": wait,
                        "bullets": scene_canon_to_bullets(beat.scene_canon, limit=3),
                        "front_id": front_id,
                        "stickiness": beat.stickiness,
                        "pillar": bool(beat.pillar),
                    }
                    if soonest is None or wait < int(soonest["due_in_minutes"]):
                        soonest = candidate
                    break

                for key in beat.set_flags:
                    flags[key] = True
                for key in beat.clear_flags:
                    flags[key] = False
                if beat.resolves_arc:
                    break
                idx = next(
                    (i for i, b in enumerate(definition.beats) if b.id == cursor),
                    -1,
                )
                if idx < 0 or idx + 1 >= len(definition.beats):
                    break
                cursor = definition.beats[idx + 1].id
        return soonest

    def front_due_now_payload(self, state: GameState) -> dict[str, Any] | None:
        """Beat already in its window at the player's place (legacy alias)."""
        live = self.front_live_payload(state)
        if live is None:
            return None
        return {
            "id": live["id"],
            "title": live["title"],
            "place": live["place"],
            "bullets": list(live["bullets"]),
        }

    def front_live_payload(self, state: GameState) -> dict[str, Any] | None:
        """Live or due-now beat at the player's place for Pass 1/2 ``extra.front_live``."""
        for front_id, runtime in state.fronts.items():
            if not runtime or runtime.status not in {"active", "diverted"}:
                continue
            if not runtime.live_beat_id:
                continue
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            beat = definition.beat_by_id.get(runtime.live_beat_id)
            if not beat or not player_at_place(state.player.location, beat.place):
                continue
            return {
                "id": beat.id,
                "title": beat.title or beat.id,
                "place": beat.place,
                "bullets": scene_canon_to_bullets(beat.scene_canon, limit=3),
                "front_id": front_id,
                "stickiness": beat.stickiness,
                "pillar": bool(beat.pillar),
                "status": "live",
                # Why the actor is still waiting; it must be re-earned each turn.
                "hold_reason": runtime.live_hold_reason,
                "hold_needs_new_fact": True,
                "interference": bool(runtime.live_interference),
                "means_inflight": bool(runtime.live_means_inflight),
            }
        info = self.next_hydratable_beat_at_player(state)
        if info is None or int(info["due_in_minutes"]) != 0:
            return None
        return {
            "id": info["id"],
            "title": info["title"],
            "place": info["place"],
            "bullets": list(info["bullets"]),
            "front_id": info["front_id"],
            "stickiness": info.get("stickiness") or "normal",
            "pillar": bool(info.get("pillar", False)),
            "status": "due",
            "hold_reason": None,
            "hold_needs_new_fact": True,
            "interference": False,
            "means_inflight": False,
        }

    def _any_live_on_site(self, state: GameState) -> bool:
        for runtime in state.fronts.values():
            if not runtime or not runtime.live_beat_id:
                continue
            if runtime.status not in {"active", "diverted"}:
                continue
            try:
                definition = self.loader.load(runtime.id)
            except FileNotFoundError:
                continue
            beat = definition.beat_by_id.get(runtime.live_beat_id)
            if beat and player_at_place(state.player.location, beat.place):
                return True
        return False

    def live_beat_place(self, state: GameState) -> str | None:
        """Place id of the on-site live beat, if any."""
        for runtime in state.fronts.values():
            if not runtime or not runtime.live_beat_id:
                continue
            try:
                definition = self.loader.load(runtime.id)
            except FileNotFoundError:
                continue
            beat = definition.beat_by_id.get(runtime.live_beat_id)
            if beat:
                return beat.place
        return None

    def commit_live_beat(
        self,
        state: GameState,
        *,
        path: str = "canon",
        note: str | None = None,
        hydrate_scene: bool = True,
    ) -> FrontOutcome:
        """Commit the live beat (canon/alt/skip/pillar_failed) or no-op for still_live.

        ``canon`` — default on_fire path when the written step happened.
        ``alt`` — other means completed the step; marks that belong to the step
        still apply, but closing wiki/location_events from scene_canon are not
        stamped as if the default means already happened.
        ``skip`` — non-pillar beat bent; advance cursor without full on_fire.
        ``pillar_failed`` — pillar step did not happen; interrupt arc (new story).
        """
        outcome = FrontOutcome()
        path_norm = (path or "canon").strip().lower()
        if path_norm == "still_live":
            return outcome

        for front_id, runtime in list(state.fronts.items()):
            if not runtime or runtime.status not in {"active", "diverted"}:
                continue
            if not runtime.live_beat_id:
                continue
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            beat = definition.beat_by_id.get(runtime.live_beat_id)
            if not beat:
                self._clear_live(runtime)
                continue

            if path_norm == "pillar_failed":
                self._fail_pillar(
                    state,
                    definition,
                    runtime,
                    beat,
                    outcome,
                    note=note,
                )
                break

            if path_norm == "skip":
                self._skip_non_pillar(
                    state,
                    definition,
                    runtime,
                    beat,
                    outcome,
                    note=note,
                )
                break

            self._commit_beat_now(
                state,
                definition,
                runtime,
                beat,
                outcome,
                path=path_norm,
                note=note,
                hydrate_scene=hydrate_scene,
            )
            break

        outcome.situations_add = _dedupe_facts(list(outcome.situations_add))
        outcome.characters_add = list(dict.fromkeys(outcome.characters_add))
        outcome.beat_summaries = list(dict.fromkeys(outcome.beat_summaries))
        for loc_id, events in list(outcome.location_events.items()):
            outcome.location_events[loc_id] = list(dict.fromkeys(events))
        return outcome

    def _fail_pillar(
        self,
        state: GameState,
        definition: FrontDefinition,
        runtime: FrontRuntime,
        beat: FrontBeat,
        outcome: FrontOutcome,
        *,
        note: str | None,
    ) -> None:
        """Pillar step missing: interrupt the front; do not fire scene_canon."""
        note_line = (note or "pillar step did not happen; arc breaks").strip()
        if note_line:
            runtime.distortion_notes.append(note_line.splitlines()[0][:200])
        outcome.beat_summaries.append(note_line.splitlines()[0][:200])
        runtime.status = "interrupted"
        runtime.interrupted_at_day = state.day
        self._clear_live(runtime)
        if self.story is not None:
            self.story.on_arc_closed(state, definition.id, forced_outcome="broken")

    def _skip_non_pillar(
        self,
        state: GameState,
        definition: FrontDefinition,
        runtime: FrontRuntime,
        beat: FrontBeat,
        outcome: FrontOutcome,
        *,
        note: str | None,
    ) -> None:
        """Non-pillar beat bent: advance the queue without stamping scene_canon."""
        note_line = (note or "non-pillar beat skipped; queue continues").strip()
        if note_line:
            runtime.distortion_notes.append(note_line.splitlines()[0][:200])
        if runtime.status == "active":
            runtime.status = "diverted"
        outcome.beat_summaries.append(note_line.splitlines()[0][:200])
        # Soft progress markers only — no wiki_writes / location_events from canon.
        for key in beat.set_flags:
            # Prefer *_done style marks so prereqs of later beats can proceed.
            if key.endswith("_done") or key.startswith("intent_"):
                runtime.flags[key] = True
        runtime.last_fired_beat = beat.id
        runtime.last_fired_at_day = state.day
        runtime.last_fired_at_minutes = state.minutes
        self._clear_live(runtime)
        if beat.resolves_arc:
            runtime.status = "resolved"
            if self.story is not None:
                self.story.on_arc_closed(state, definition.id)
        elif not self._advance_cursor(definition, runtime):
            runtime.status = "resolved"
            if self.story is not None:
                self.story.on_arc_closed(state, definition.id)

    @staticmethod
    def _clear_live(runtime: FrontRuntime) -> None:
        runtime.live_beat_id = None
        runtime.live_started_abs = None
        runtime.live_hold_reason = None
        runtime.live_progress_key = None
        runtime.live_interference = False
        runtime.live_means_inflight = False

    def live_runtime_on_site(self, state: GameState) -> FrontRuntime | None:
        """Runtime whose live beat is at the player's place, if any."""
        for runtime in state.fronts.values():
            if not runtime or not runtime.live_beat_id:
                continue
            if runtime.status not in {"active", "diverted"}:
                continue
            try:
                definition = self.loader.load(runtime.id)
            except FileNotFoundError:
                continue
            beat = definition.beat_by_id.get(runtime.live_beat_id)
            if beat and player_at_place(state.player.location, beat.place):
                return runtime
        return None

    def live_beat_definition(
        self, state: GameState
    ) -> tuple[FrontRuntime, FrontDefinition, FrontBeat] | None:
        """On-site live runtime + definition + beat, if any."""
        runtime = self.live_runtime_on_site(state)
        if runtime is None or not runtime.live_beat_id:
            return None
        try:
            definition = self.loader.load(runtime.id)
        except FileNotFoundError:
            return None
        beat = definition.beat_by_id.get(runtime.live_beat_id)
        if not beat:
            return None
        return runtime, definition, beat

    def live_commit_path(
        self,
        state: GameState,
        *,
        proposed: str | None,
        progress_key: str,
        hold_reason: str | None = None,
        engagement: bool = False,
        means_inflight: bool = False,
        allow_land: bool = False,
    ) -> str | None:
        """Decide how a live beat resolves from what this turn actually produced.

        Engagement (dialogue with the actor, cast, scene play) or a means still
        in flight keeps ``still_live``. Empty progress alone does **not** force
        canon while the PC is still playing the scene. Landing (canon/alt) needs
        an explicit propose or ``allow_land`` (e.g. wait while means is inflight).
        """
        packed = self.live_beat_definition(state)
        if packed is None:
            return None
        runtime, _definition, beat = packed
        proposed_norm = (proposed or "").strip().lower() or "still_live"

        if means_inflight:
            runtime.live_means_inflight = True

        if proposed_norm == "pillar_failed":
            if beat.pillar:
                return "pillar_failed"
            # Non-pillar "failed" written scene → skip ahead, queue continues.
            return "skip"

        if proposed_norm == "skip":
            return "skip" if not beat.pillar else "pillar_failed"

        # Landing: explicit canon/alt when allowed (wait while inflight, or no inflight).
        if proposed_norm in {"canon", "alt"}:
            if runtime.live_means_inflight and not allow_land and proposed_norm != "alt":
                # Hostile act still in the air — do not stamp on_fire yet.
                if hold_reason is not None:
                    runtime.live_hold_reason = (hold_reason or "").strip() or None
                return "still_live"
            runtime.live_means_inflight = False
            if runtime.live_interference and proposed_norm == "canon":
                return "alt"
            return "alt" if runtime.live_interference else proposed_norm

        # still_live (or unknown): hold if the scene is still being played.
        renew = (
            engagement
            or runtime.live_means_inflight
            or bool(progress_key and progress_key != (runtime.live_progress_key or ""))
        )
        if renew:
            if progress_key and progress_key != (runtime.live_progress_key or ""):
                runtime.live_progress_key = progress_key
            if hold_reason is not None:
                runtime.live_hold_reason = (hold_reason or "").strip() or None
            return "still_live"

        # Empty wait / allow_land with nothing left to play: actor may resolve.
        # Do not force canon on mere progress-key echo while the window is open.
        if allow_land:
            if runtime.live_interference:
                return "alt"
            return "canon"
        return "still_live"

    def apply_impacts(self, state: GameState, impacts: list[FrontImpact]) -> None:
        """Apply typed front impacts from present review (phase 2)."""
        layer3_ids = set()
        for front_id, runtime in state.fronts.items():
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            for item in definition.intents_layer3:
                if isinstance(item, dict) and item.get("id"):
                    layer3_ids.add(str(item["id"]))

        for impact in impacts:
            if impact.effect in (None, "null"):
                continue
            # layer 3 intents cannot be killed by local PC action
            if impact.intent_id in layer3_ids:
                continue
            runtime = state.fronts.get(impact.front_id)
            if not runtime:
                continue
            # A typed impact on a live beat is the "clear interference" signal:
            # the default means gets bent (alt) instead of playing out as canon.
            if runtime.live_beat_id:
                runtime.live_interference = True
            intent_flag = f"intent_{impact.intent_id}"
            if impact.effect == "block":
                if intent_flag in runtime.flags:
                    runtime.flags[intent_flag] = False
                for key, value in (impact.flags_set or {}).items():
                    runtime.flags[str(key)] = bool(value)
                if impact.evidence:
                    runtime.distortion_notes.append(f"block:{impact.intent_id}:{impact.evidence}")
            elif impact.effect == "distort":
                if runtime.status == "active":
                    runtime.status = "diverted"
                for key, value in (impact.flags_set or {}).items():
                    runtime.flags[str(key)] = bool(value)
                if impact.evidence:
                    runtime.distortion_notes.append(f"distort:{impact.intent_id}:{impact.evidence}")

    def build_canon_timeline(self, state: GameState) -> ArcTimelineResponse:
        """Ordered canonical beats for active fronts, with progress status.

        ``current`` = fase in corso nel mondo:
        - se il beat sul cursore e' gia' dovuto sull'orologio (anche se deferred
          in presenza del PG), quello e' ``current``;
        - altrimenti ``current`` e' l'ultimo materializzato.
        """
        fronts: list[ArcTimelineFront] = []
        now_abs = absolute_minutes(state.day, state.minutes)
        for front_id, runtime in state.fronts.items():
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            fired = self._fired_beat_ids(definition, runtime)
            cursor_idx = next(
                (i for i, b in enumerate(definition.beats) if b.id == runtime.cursor_beat),
                -1,
            )
            cursor_beat = definition.beat_by_id.get(runtime.cursor_beat)
            divert_dead_end = (
                runtime.status == "diverted"
                and runtime.cursor_beat not in fired
                and not self._has_next(definition, runtime)
            )
            cursor_due = bool(
                cursor_beat
                and runtime.status in {"active", "diverted"}
                and runtime.cursor_beat not in fired
                and now_abs >= self._beat_due(runtime, cursor_beat)
                and not divert_dead_end
            )
            beats_out: list[ArcTimelineBeat] = []
            for i, beat in enumerate(definition.beats):
                due_day, _due_minutes = day_minutes_from_abs(self._beat_due(runtime, beat))
                due_time = format_due_day(due_day)
                if runtime.status == "interrupted" and beat.id not in fired:
                    status: str = "skipped"
                elif runtime.live_beat_id and beat.id == runtime.live_beat_id:
                    status = "live"
                elif 0 <= i < cursor_idx and beat.id not in fired:
                    status = "skipped"
                elif (
                    runtime.status == "diverted"
                    and beat.id == runtime.cursor_beat
                    and beat.id not in fired
                    and not self._has_next(definition, runtime)
                ):
                    status = "skipped"
                elif cursor_due and beat.id == runtime.cursor_beat:
                    status = "current"
                elif runtime.last_fired_beat and beat.id == runtime.last_fired_beat:
                    if cursor_due or runtime.status == "resolved":
                        status = "done"
                    else:
                        status = "current"
                elif beat.id in fired:
                    status = "done"
                elif (
                    not runtime.last_fired_beat
                    and beat.id == runtime.cursor_beat
                    and runtime.status in {"active", "diverted"}
                ):
                    status = "current"
                elif runtime.status == "resolved":
                    status = "done" if beat.id in fired else "skipped"
                else:
                    status = "upcoming"
                bullets = scene_canon_to_bullets(beat.scene_canon, limit=1)
                beats_out.append(
                    ArcTimelineBeat(
                        id=beat.id,
                        title=beat.title,
                        place=beat.place,
                        status=status,  # type: ignore[arg-type]
                        summary=bullets[0] if bullets else "",
                        hours_after_previous=beat.hours_after_previous,
                        estimated_day=due_day,
                        due_time=due_time,
                        pillar=bool(beat.pillar),
                    )
                )
            fronts.append(
                ArcTimelineFront(
                    id=definition.id,
                    name=definition.name,
                    status=runtime.status,
                    cursor_beat=runtime.cursor_beat,
                    last_fired_beat=runtime.last_fired_beat,
                    beats=beats_out,
                )
            )
        return ArcTimelineResponse(fronts=fronts)

    def build_prompt_slice(self, state: GameState) -> str:
        blocks: list[str] = []
        for front_id, runtime in state.fronts.items():
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            previous = (
                definition.beat_by_id.get(runtime.last_fired_beat)
                if runtime.last_fired_beat
                else None
            )
            pending = self._pending_beat(definition, runtime)

            lines = [
                f"## Arco attivo: {definition.name} ({runtime.id})",
                f"Stato: {runtime.status}",
            ]
            if definition.temporal_constraints:
                lines.append("Vincoli temporali (prevalgono sulle schede complete):")
                lines.extend(f"  - {item}" for item in definition.temporal_constraints)
            if previous:
                lines.append(f"Ultimo fatto materializzato: {previous.title} ({previous.id})")
            if runtime.status == "interrupted":
                lines.append(
                    "Arco INTERROTTO: non fingere la timeline canone. "
                    "Narra solo conseguenze coerenti con flags/wiki."
                )
            elif pending and runtime.status in {"active", "diverted"}:
                due_day, _due_min = day_minutes_from_abs(self._beat_due(runtime, pending))
                lines.append(
                    f"Prossimo fatto atteso (se nessuno interferisce): {pending.title} "
                    f"(finestra {format_due_day(due_day)}; scegli tu l'ora narrativamente)"
                )
                bullets = scene_canon_to_bullets(pending.scene_canon, limit=2)
                for b in bullets:
                    lines.append(f"  - [NARRATOR_ONLY] {b}")
                if pending.prompt_inject:
                    lines.append(pending.prompt_inject.strip())
                now_abs = absolute_minutes(state.day, state.minutes)
                if runtime.live_beat_id == pending.id:
                    lines.append(
                        "Beat LIVE sul place del PG: pressione in corso QUI "
                        f"(`canon_facts.location`; place={pending.place}). "
                        "Il metodo di default e' in scene_canon ma NON e' ancora commitato. "
                        "VIETATO narrarlo come gia' accaduto altrove / altro settore."
                    )
                    if pending.pillar:
                        lines.append(
                            "Questo beat e' un PILASTRO: il passo deve accadere "
                            "(mezzo di default o altro). Se il passo non accade → "
                            "pillar_failed (arco spezzato). Un mezzo alla volta; "
                            "vietato spam del mezzo di default fallito."
                        )
                    lines.append(
                        "Onora still_live se il PG gioca sulla scena (dialogo con "
                        "l'attore, cast, magia, mezzo in volo). Un atto ostile nuovo "
                        "si telegrafa (means_inflight); non commitare on_fire finche' "
                        "non atterra. Wait su mezzo in volo puo' farlo atterrare."
                    )
                    if runtime.live_means_inflight:
                        lines.append(
                            "Mezzo GIA' in volo: non rifare lo stesso telegrafo; "
                            "il PG puo' intercettare o aspettare l'impatto."
                        )
                    if runtime.live_hold_reason:
                        lines.append(f"Motivo dell'attesa in corso: {runtime.live_hold_reason}")
                elif now_abs >= self._beat_due(runtime, pending):
                    lines.append(
                        "Fatto GIA' nella finestra sul place del PG: apri la pressione QUI "
                        f"(`canon_facts.location`; place={pending.place}). "
                        "Non chiudere l'esito altrove. Commit solo se la scena lo risolve "
                        "(canon/alt); altrimenti still_live."
                    )

            cast_now, cast_not_yet = self._cast_split(definition, runtime, state=state)
            if cast_now:
                lines.append(
                    f"Cast sul luogo (nearby, NON interlocutori automatici): {', '.join(cast_now)}"
                )
            if cast_not_yet:
                lines.append(f"Non ancora in gioco: {', '.join(cast_not_yet)}")
            if previous and previous.ambient:
                lines.append(
                    "Ambient sul place dell'ultimo fatto: "
                    + ", ".join(previous.ambient)
                    + " — interlocutori generici (guardia, soldato), non i nearby nominati. "
                    "In allerta/fortezza possono FERMARE o SQUADRARE il PG senza essere in present."
                )
            if previous:
                lines.append(
                    "Nearby nominati: in prosa usa SOLO nomi in `extra.player_known`; "
                    "altrimenti ruoli (sergente, caporale) + id NARRATOR_ONLY. "
                    "NON farli comparire in un altro place."
                )
            if pending and pending.ambient:
                lines.append(
                    "Ambient del prossimo fatto: " + ", ".join(pending.ambient)
                )
            if runtime.distortion_notes:
                lines.append("Distorsioni: " + "; ".join(runtime.distortion_notes[-3:]))
            if definition.intents_layer3:
                summaries = [
                    str(i.get("summary") or i.get("id"))
                    for i in definition.intents_layer3
                    if isinstance(i, dict)
                ]
                lines.append("Sfondo (strato 3, non spegnibile localmente): " + " | ".join(summaries[:3]))
            lines.append(
                "VIETATO: anticipare i FATTI del prossimo beat (on_fire, collassi, morti, "
                "chiusure); anticipare il GIORNO del fatto; far spuntare NPC "
                "fuori luogo; far parlare i nearby nominati se il PG parla a una "
                "guardia/ruolo ambient. "
                "LICEITO: aspetto wiki di `extra.distant_cast` se il PG osserva quella "
                "direzione/presenza (distant: niente dialogo, niente nome proprio se "
                "assente da player_known). "
                "L'ora nella giornata del fatto dovuto la scegli tu. "
                "NON copiare scene_canon come dialogo NPC."
            )
            if runtime.status == "diverted":
                lines.append("Arco DISTORTO: stessi punti possibili, aggiusta tono/dettaglio.")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def build_temporal_context(self, state: GameState) -> str:
        """Return era constraints that override future-biography character cards."""
        constraints: list[str] = []
        for front_id, runtime in state.fronts.items():
            if runtime.status not in {"active", "diverted"}:
                continue
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            constraints.extend(definition.temporal_constraints)
        return "\n".join(dict.fromkeys(constraints))

    def relevant_cast_wiki_ids(self, state: GameState) -> list[str]:
        ids: list[str] = []
        for front_id, runtime in state.fronts.items():
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            fired_ids = self._fired_beat_ids(definition, runtime)
            for member in definition.cast.values():
                if not member.wiki:
                    continue
                if member.appear_from in fired_ids and knows(state, member.wiki):
                    ids.append(member.wiki)
        return list(dict.fromkeys(ids))

    def distant_cast_entries(self, state: GameState) -> list[dict[str, str]]:
        """Canon cast of the pending beat, visible at distance but not yet in present.

        When the PG is at the pending beat's place, members in ``cast_in_world``
        whose ``appear_from`` has not fired yet are returned as distant (wiki
        aspect may enter the prompt; they do not speak / join present).
        """
        present = {
            str(cid).strip().casefold()
            for cid in (state.characters_active or [])
            if str(cid or "").strip()
        }
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for front_id, runtime in state.fronts.items():
            if runtime.status not in {"active", "diverted"}:
                continue
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            pending = self._pending_beat(definition, runtime)
            if pending is None:
                continue
            if not player_at_place(state.player.location, pending.place):
                continue
            fired_ids = self._fired_beat_ids(definition, runtime)
            # Distant = observable until Pass 1 joins them (dialogue / engagement).
            # ``narrate_symptoms_or_edge`` only skips auto cast_acting on fire/hydrate;
            # it does not forbid present_join when the PC opens talk.
            for cast_key in pending.cast_in_world:
                member = definition.cast.get(cast_key)
                if not member or not member.wiki:
                    continue
                if member.appear_from in fired_ids:
                    continue
                wiki = str(member.wiki).strip()
                key = wiki.casefold()
                if not wiki or key in seen or key in present:
                    continue
                seen.add(key)
                out.append(
                    {
                        "id": wiki,
                        "role": (member.role or "").strip(),
                    }
                )
        return out

    def distant_cast_wiki_ids(self, state: GameState) -> list[str]:
        return [e["id"] for e in self.distant_cast_entries(state)]

    def cast_role_map(self, state: GameState) -> dict[str, str]:
        """wiki id → role string from active front cast definitions."""
        roles: dict[str, str] = {}
        for front_id, runtime in state.fronts.items():
            if runtime.status not in {"active", "diverted", "resolved", "interrupted"}:
                continue
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            for member in definition.cast.values():
                wiki = (member.wiki or member.key or "").strip().lower()
                if wiki and member.role:
                    roles.setdefault(wiki, member.role)
        return roles

    def ensure_scene_at_player(self, state: GameState) -> FrontOutcome:
        """Stamp atmosphere/ambient/nearby when the PG is at a fired beat's place.

        Does NOT force named cast into present (acting). Nearby stays offscreen-at-place.
        """
        outcome = FrontOutcome()
        for front_id, runtime in state.fronts.items():
            if runtime.status not in {"active", "diverted"}:
                continue
            if not runtime.last_fired_beat:
                continue
            try:
                definition = self.loader.load(front_id)
            except FileNotFoundError:
                continue
            beat = definition.beat_by_id.get(runtime.last_fired_beat)
            if not beat or not player_at_place(state.player.location, beat.place):
                continue
            hydrate = self._hydrate_collect(
                definition, beat, player_present=True, acting_cast=False
            )
            place_key = beat.place
            loc_rt = state.locations.get(place_key)
            if not loc_rt or not loc_rt.atmosphere:
                for loc_id, atm in hydrate["location_atmosphere"].items():
                    outcome.location_atmosphere[loc_id] = atm
            if not loc_rt or not loc_rt.events:
                for loc_id, events in hydrate["location_events"].items():
                    outcome.location_events.setdefault(loc_id, []).extend(events)
            if not loc_rt or not loc_rt.ambient:
                for loc_id, roles in hydrate["location_ambient"].items():
                    outcome.location_ambient.setdefault(loc_id, []).extend(roles)
            for cid, loc in hydrate["characters_nearby"].items():
                if cid not in state.characters_active:
                    outcome.characters_nearby[cid] = loc
                    outcome.character_locations[cid] = loc
            if not state.situations:
                if hydrate["situations_add"]:
                    outcome.situations_add.extend(hydrate["situations_add"])
                elif loc_rt and loc_rt.events:
                    outcome.situations_add.extend(
                        [
                            NpcKnowledgeFact(
                                id=slugify_fact_id(f"front_{beat.id}_{i}_{b}"),
                                summary=b,
                            )
                            for i, b in enumerate(loc_rt.events)
                            if (b or "").strip()
                        ]
                    )
            if (
                outcome.location_events
                or outcome.location_atmosphere
                or outcome.location_ambient
                or outcome.characters_nearby
            ):
                outcome.beat_summaries.extend(
                    hydrate.get("location_events", {}).get(place_key) or []
                )
        outcome.beat_summaries = list(dict.fromkeys(outcome.beat_summaries))
        for loc_id, events in list(outcome.location_events.items()):
            outcome.location_events[loc_id] = list(dict.fromkeys(events))
        for loc_id, roles in list(outcome.location_ambient.items()):
            outcome.location_ambient[loc_id] = list(dict.fromkeys(roles))
        if (
            outcome.location_events
            or outcome.location_atmosphere
            or outcome.location_ambient
            or outcome.situations_add
            or outcome.characters_nearby
        ):
            apply_front_outcome(state, outcome)
        return outcome

    def _fired_beat_ids(self, definition: FrontDefinition, runtime: FrontRuntime) -> set[str]:
        """Beats up to and including last_fired_beat."""
        if not runtime.last_fired_beat:
            return set()
        fired: set[str] = set()
        for beat in definition.beats:
            fired.add(beat.id)
            if beat.id == runtime.last_fired_beat:
                break
        return fired

    def _pending_beat(
        self, definition: FrontDefinition, runtime: FrontRuntime
    ) -> FrontBeat | None:
        """Next expected beat for prompts / distant cast (same rules as prompt slice)."""
        current = definition.beat_by_id.get(runtime.cursor_beat)
        if current is None:
            return None
        if runtime.last_fired_beat and runtime.cursor_beat == runtime.last_fired_beat:
            if runtime.status == "resolved" or not self._has_next(definition, runtime):
                return None
        return current

    def _cast_split(
        self,
        definition: FrontDefinition,
        runtime: FrontRuntime,
        *,
        state: GameState | None = None,
    ) -> tuple[list[str], list[str]]:
        fired = self._fired_beat_ids(definition, runtime)
        now: list[str] = []
        later: list[str] = []
        for key, member in definition.cast.items():
            wiki = member.wiki or key
            role = member.role or ""
            if state is not None:
                if is_named(state, wiki):
                    display = f"{wiki} ({role})" if role else wiki
                else:
                    display = label(state, wiki, role or "figura")
            else:
                display = f"{wiki} ({role})" if role else wiki
            if member.appear_from in fired:
                now.append(display)
            else:
                later.append(display)
        return now, later

    def _prereq_ok(self, flags: dict[str, bool], beat: FrontBeat) -> bool:
        for key in beat.prereq_all:
            if not flags.get(key, False):
                return False
        for key in beat.prereq_none:
            if flags.get(key, False):
                return False
        return True

    def _matching_variant(self, definition: FrontDefinition, runtime: FrontRuntime, beat_id: str):
        for variant in definition.variants:
            if beat_id not in variant.replaces:
                continue
            if not variant.when_flag:
                continue
            actual = bool(runtime.flags.get(variant.when_flag, False))
            if actual == variant.when_equals:
                return variant
        return None

    def _advance_cursor(self, definition: FrontDefinition, runtime: FrontRuntime) -> bool:
        idx = next((i for i, b in enumerate(definition.beats) if b.id == runtime.cursor_beat), -1)
        if idx < 0 or idx + 1 >= len(definition.beats):
            return False
        runtime.cursor_beat = definition.beats[idx + 1].id
        return True

    def _has_next(self, definition: FrontDefinition, runtime: FrontRuntime) -> bool:
        idx = next((i for i, b in enumerate(definition.beats) if b.id == runtime.cursor_beat), -1)
        return 0 <= idx < len(definition.beats) - 1

    def _commit_beat_now(
        self,
        state: GameState,
        definition: FrontDefinition,
        runtime: FrontRuntime,
        beat: FrontBeat,
        outcome: FrontOutcome,
        *,
        path: str,
        note: str | None,
        hydrate_scene: bool,
    ) -> None:
        """Fire the beat and advance the cursor (shared by clock and commit paths)."""
        note_line = ""
        if path == "alt":
            if runtime.status == "active":
                runtime.status = "diverted"
            note_line = (note or "alt path: default means bent; pressure continues").strip()
            if note_line:
                runtime.distortion_notes.append(note_line.splitlines()[0][:200])

        fire_data = self._fire_collect(
            state,
            definition,
            runtime,
            beat,
            hydrate_scene=hydrate_scene,
        )
        if path == "alt":
            # Do not stamp closing location_events as if the default means already
            # happened off-site; keep nearby/ambient/atmosphere pressure.
            fire_data = dict(fire_data)
            fire_data["location_events"] = {}
            fire_data["wiki_patches"] = []
            bullets = scene_canon_to_bullets(beat.scene_canon, limit=1)
            fire_data["beat_summaries"] = [
                note_line if note_line else (bullets[0] if bullets else beat.title)
            ]

        self._merge_fire_into_outcome(outcome, fire_data, beat_id=beat.id)
        self._clear_live(runtime)

        if beat.resolves_arc:
            runtime.status = "resolved"
            if self.story is not None:
                self.story.on_arc_closed(state, definition.id)
        elif not self._advance_cursor(definition, runtime):
            runtime.status = "resolved"
            if self.story is not None:
                self.story.on_arc_closed(state, definition.id)

    def _enter_live(
        self,
        state: GameState,
        runtime: FrontRuntime,
        beat: FrontBeat,
        outcome: FrontOutcome,
        *,
        now_abs: int,
    ) -> None:
        """Open on-site participation: pressure hydrate without committing marks/wiki."""
        runtime.live_beat_id = beat.id
        runtime.live_started_abs = now_abs
        outcome.live_beats.append(beat.id)
        try:
            definition = self.loader.load(runtime.id)
        except FileNotFoundError:
            return
        bullets = scene_canon_to_bullets(beat.scene_canon, limit=2)
        hydrate = self._hydrate_collect(
            definition,
            beat,
            bullets,
            player_present=True,
            acting_cast=False,
            pressure_only=True,
        )
        for loc_id, atm in hydrate["location_atmosphere"].items():
            # Prefer player location stamp when subplace
            outcome.location_atmosphere[loc_id] = atm
            if state.player.location and state.player.location != loc_id:
                if player_at_place(state.player.location, beat.place):
                    outcome.location_atmosphere[state.player.location] = atm
        for loc_id, roles in hydrate["location_ambient"].items():
            outcome.location_ambient.setdefault(loc_id, [])
            outcome.location_ambient[loc_id] = list(
                dict.fromkeys(outcome.location_ambient[loc_id] + list(roles))
            )
            if state.player.location and player_at_place(state.player.location, beat.place):
                pl = state.player.location
                outcome.location_ambient.setdefault(pl, [])
                outcome.location_ambient[pl] = list(
                    dict.fromkeys(outcome.location_ambient[pl] + list(roles))
                )
        for cid, loc in hydrate["characters_nearby"].items():
            outcome.characters_nearby[cid] = loc
            outcome.character_locations[cid] = loc
        # No location_events / wiki / marks — beat not committed.

    @staticmethod
    def _merge_fire_into_outcome(
        outcome: FrontOutcome,
        fire_data: dict[str, Any],
        *,
        beat_id: str,
    ) -> None:
        outcome.fired_beats.append(beat_id)
        outcome.wiki_patches.extend(fire_data.get("wiki_patches") or [])
        outcome.beat_summaries.extend(fire_data.get("beat_summaries") or [])
        outcome.situations_add.extend(
            coerce_fact_list(fire_data.get("situations_add") or [])
        )
        outcome.characters_add.extend(fire_data.get("characters_add") or [])
        for cid, loc in (fire_data.get("characters_nearby") or {}).items():
            outcome.characters_nearby[cid] = loc
        for loc_id, roles in (fire_data.get("location_ambient") or {}).items():
            outcome.location_ambient.setdefault(loc_id, [])
            outcome.location_ambient[loc_id] = list(
                dict.fromkeys(outcome.location_ambient[loc_id] + list(roles))
            )
        for loc_id, events in (fire_data.get("location_events") or {}).items():
            outcome.location_events.setdefault(loc_id, []).extend(events)
        for loc_id, atmosphere in (fire_data.get("location_atmosphere") or {}).items():
            outcome.location_atmosphere[loc_id] = atmosphere
        for cid, loc in (fire_data.get("character_locations") or {}).items():
            outcome.character_locations[cid] = loc

    def _fire_collect(
        self,
        state: GameState,
        definition: FrontDefinition,
        runtime: FrontRuntime,
        beat: FrontBeat,
        *,
        hydrate_scene: bool = True,
    ) -> dict[str, Any]:
        """Mutate front runtime flags/cursor markers; collect scene/wiki side-effects."""
        for key in beat.set_flags:
            runtime.flags[key] = True
        for key in beat.clear_flags:
            runtime.flags[key] = False

        due_day, due_minutes = day_minutes_from_abs(self._beat_due(runtime, beat))
        runtime.last_fired_at_day = due_day
        runtime.last_fired_at_minutes = due_minutes
        runtime.last_fired_beat = beat.id

        wiki_patches: list[dict[str, Any]] = list(beat.wiki_writes or [])
        bullets = scene_canon_to_bullets(beat.scene_canon, limit=3)
        on_site = player_at_place(state.player.location, beat.place)
        # Always stamp world/place facts; nearby cast is in the world even if PG absent.
        hydrate = self._hydrate_collect(
            definition,
            beat,
            bullets,
            player_present=bool(hydrate_scene and on_site),
            acting_cast=bool(hydrate_scene and on_site),
        )
        data: dict[str, Any] = {
            "wiki_patches": wiki_patches,
            "beat_summaries": list(bullets),
            "situations_add": hydrate["situations_add"] if (hydrate_scene and on_site) else [],
            "characters_add": hydrate["characters_add"],
            "characters_nearby": hydrate["characters_nearby"],
            "location_events": hydrate["location_events"],
            "location_atmosphere": hydrate["location_atmosphere"],
            "location_ambient": hydrate["location_ambient"],
            "character_locations": hydrate["character_locations"],
        }
        return data

    def _hydrate_collect(
        self,
        definition: FrontDefinition,
        beat: FrontBeat,
        bullets: list[str] | None = None,
        *,
        player_present: bool = False,
        acting_cast: bool = False,
        pressure_only: bool = False,
    ) -> dict[str, Any]:
        """Build place facts + nearby cast; acting cast only when requested on-site.

        ``pressure_only``: atmosphere/ambient/nearby without closing location_events.
        """
        bullets = bullets if bullets is not None else scene_canon_to_bullets(beat.scene_canon, limit=3)
        characters_add: list[str] = []
        characters_nearby: dict[str, str] = {}
        character_locations: dict[str, str] = {}
        location_events: dict[str, list[str]] = {}
        location_atmosphere: dict[str, str] = {}
        location_ambient: dict[str, list[str]] = {}

        if bullets:
            location_atmosphere[beat.place] = bullets[0][:120]
            if not pressure_only:
                location_events[beat.place] = list(bullets)
        if beat.ambient:
            location_ambient[beat.place] = list(beat.ambient)

        # Symptoms/edge beats skip auto cast_acting on fire/hydrate; dialogue can
        # still promote via present_join (Pass 1 / pipeline engagement).
        symptoms_only = beat.raw.get("if_player_present") == "narrate_symptoms_or_edge"

        for cast_key in beat.cast_in_world:
            member = definition.cast.get(cast_key)
            if not member or not member.wiki:
                continue
            place = member.default_location or beat.place
            characters_nearby[member.wiki] = place
            character_locations[member.wiki] = place

        if acting_cast and player_present:
            for cast_key in beat.cast_acting:
                member = definition.cast.get(cast_key)
                if not member or not member.wiki:
                    continue
                if symptoms_only:
                    continue
                characters_add.append(member.wiki)
                place = member.default_location or beat.place
                character_locations[member.wiki] = place
                characters_nearby.pop(member.wiki, None)

        situations: list[NpcKnowledgeFact] = []
        if player_present:
            situations = [
                NpcKnowledgeFact(
                    id=slugify_fact_id(f"front_{beat.id}_{i}_{b}"),
                    summary=b,
                )
                for i, b in enumerate(bullets)
                if (b or "").strip()
            ]

        return {
            "situations_add": situations,
            "characters_add": characters_add,
            "characters_nearby": characters_nearby,
            "character_locations": character_locations,
            "location_events": location_events,
            "location_atmosphere": location_atmosphere,
            "location_ambient": location_ambient,
        }
