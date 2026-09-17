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
        self.tick(state, 0, front_ids=[definition.id], hydrate_scene=False)

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
    ) -> FrontOutcome:
        """Advance front runtime; return scene/wiki side-effects without applying them.

        Mutates front cursors/flags/status only. Does not touch situations,
        characters_active, locations, or wiki files.
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

                fire_data = self._fire_collect(
                    state,
                    definition,
                    runtime,
                    beat,
                    hydrate_scene=hydrate_scene,
                )
                outcome.fired_beats.append(beat.id)
                outcome.wiki_patches.extend(fire_data["wiki_patches"])
                outcome.beat_summaries.extend(fire_data["beat_summaries"])
                outcome.situations_add.extend(
                    coerce_fact_list(fire_data["situations_add"])
                )
                outcome.characters_add.extend(fire_data["characters_add"])
                for cid, loc in fire_data.get("characters_nearby", {}).items():
                    outcome.characters_nearby[cid] = loc
                for loc_id, roles in fire_data.get("location_ambient", {}).items():
                    outcome.location_ambient.setdefault(loc_id, [])
                    outcome.location_ambient[loc_id] = list(
                        dict.fromkeys(outcome.location_ambient[loc_id] + list(roles))
                    )
                for loc_id, events in fire_data["location_events"].items():
                    outcome.location_events.setdefault(loc_id, []).extend(events)
                for loc_id, atmosphere in fire_data["location_atmosphere"].items():
                    outcome.location_atmosphere[loc_id] = atmosphere
                for cid, loc in fire_data["character_locations"].items():
                    outcome.character_locations[cid] = loc

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
    ) -> list[str]:
        """Backward-compatible tick: resolve, apply scene hydrate, write wiki."""
        outcome = self.resolve_tick(
            state,
            delta_minutes,
            front_ids=front_ids,
            hydrate_scene=hydrate_scene,
            defer_presence=defer_presence,
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
        """Minutes until the next beat that would hydrate at the player's place."""
        soonest: int | None = None
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
                    if soonest is None or wait < soonest:
                        soonest = wait
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
                if now_abs >= self._beat_due(runtime, pending):
                    lines.append(
                        "Fatto GIA' nella finestra del giorno: materializzalo in questa "
                        "risposta se il PG e' nel place. Scegli l'ora/atmosfera che ha "
                        "piu' senso per la scena (non citare orologi o 'Giorno N' nel text)."
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
                "meteoriti, chiusure); anticipare il GIORNO del fatto; far spuntare NPC "
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
            symptoms = pending.raw.get("if_player_present") == "narrate_symptoms_or_edge"
            for cast_key in pending.cast_in_world:
                member = definition.cast.get(cast_key)
                if not member or not member.wiki:
                    continue
                if symptoms and cast_key in {"ainz", "albedo"}:
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
    ) -> dict[str, Any]:
        """Build place facts + nearby cast; acting cast only when requested on-site."""
        bullets = bullets if bullets is not None else scene_canon_to_bullets(beat.scene_canon, limit=3)
        characters_add: list[str] = []
        characters_nearby: dict[str, str] = {}
        character_locations: dict[str, str] = {}
        location_events: dict[str, list[str]] = {}
        location_atmosphere: dict[str, str] = {}
        location_ambient: dict[str, list[str]] = {}

        if bullets:
            location_atmosphere[beat.place] = bullets[0][:120]
            location_events[beat.place] = list(bullets)
        if beat.ambient:
            location_ambient[beat.place] = list(beat.ambient)

        for cast_key in beat.cast_in_world:
            member = definition.cast.get(cast_key)
            if not member or not member.wiki:
                continue
            if cast_key in {"ainz", "albedo"} and beat.raw.get("if_player_present") == "narrate_symptoms_or_edge":
                continue
            place = member.default_location or beat.place
            characters_nearby[member.wiki] = place
            character_locations[member.wiki] = place

        if acting_cast and player_present:
            for cast_key in beat.cast_acting:
                member = definition.cast.get(cast_key)
                if not member or not member.wiki:
                    continue
                if cast_key in {"ainz", "albedo"} and beat.raw.get("if_player_present") == "narrate_symptoms_or_edge":
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
