"""Story / era runtime: chronicle, arc close, succession, prompt slice."""

from __future__ import annotations

from typing import Any, Literal

from app.config import settings
from app.models.game_state import (
    ArcRecord,
    ChronicleEntry,
    FrontRuntime,
    GameState,
    WorldPressure,
)
from app.story.era_loader import EraDefinition, EraLoader
from app.story.front_loader import FrontDefinition, FrontLoader
from app.player.knowledge import seed_player_lens as seed_lens_impl
from app.wiki.wiki_writer import WikiWriter

ArcOutcome = Literal["canon", "weak", "diverted", "broken", "lapsed"]

_REACH_RANK = {
    "none": 0,
    "local": 1,
    "regional": 2,
    "national": 3,
    "world": 4,
}


def epoch_overlay_ids(state: GameState) -> list[str]:
    """Overlay ids: era first, then active/diverted fronts (later override)."""
    ids: list[str] = []
    if state.story.era:
        ids.append(state.story.era)
    for front_id, runtime in state.fronts.items():
        if runtime and runtime.status in {"active", "diverted"}:
            ids.append(front_id)
    return list(dict.fromkeys(ids))


def player_is_insider(state: GameState, era: EraDefinition | None) -> bool:
    if not era:
        return False
    pid = (state.player.resolved_character_id() or "").strip().lower()
    if not pid:
        return False
    return pid in {x.strip().lower() for x in era.insiders}


def filter_chronicle_for_player(
    entries: list[ChronicleEntry],
    *,
    is_insider: bool,
    min_reach: str = "local",
) -> list[ChronicleEntry]:
    """Drop secrets (unless insider) and entries below min_reach."""
    floor = _REACH_RANK.get(min_reach, 1)
    out: list[ChronicleEntry] = []
    for entry in entries:
        if entry.secret or entry.reach == "none":
            if is_insider:
                out.append(entry)
            continue
        if _REACH_RANK.get(entry.reach, 0) >= floor:
            out.append(entry)
    return out


class StoryEngine:
    def __init__(
        self,
        *,
        fronts: Any = None,
        wiki: WikiWriter | None = None,
        era_loader: EraLoader | None = None,
        front_loader: FrontLoader | None = None,
        llm: Any = None,
    ) -> None:
        self.fronts = fronts
        self.wiki = wiki or WikiWriter()
        self.era_loader = era_loader
        self.front_loader = front_loader or FrontLoader()
        self.llm = llm

    def _era(self, state: GameState) -> EraDefinition | None:
        if not state.story.era:
            return None
        loader = self.era_loader or EraLoader(story_id=state.story_id)
        try:
            return loader.load(state.story.era)
        except (FileNotFoundError, ValueError):
            return None

    def seed_era(
        self,
        state: GameState,
        era_id: str,
        *,
        activate_entry: bool = True,
        fire_start: bool = True,
    ) -> EraDefinition:
        """Apply era photograph to state and optionally activate entry_arc."""
        loader = self.era_loader or EraLoader(story_id=state.story_id)
        era = loader.load(era_id)
        state.story.era = era.id
        state.story.world_flags = dict(era.world_flags)
        state.story.current_arc = None
        state.story.chronicle = []
        for line in era.chronicle:
            day = None
            if line.day_offset is not None:
                day = era.start_day + int(line.day_offset)
            state.story.chronicle.append(
                ChronicleEntry(
                    id=line.id,
                    summary=line.summary,
                    reach=line.reach,  # type: ignore[arg-type]
                    secret=line.secret,
                    source="canon_digest",
                    day=day,
                )
            )
        state.day = era.start_day
        state.minutes = era.start_minutes
        if era.start_location:
            state.player.location = era.start_location
        self.wiki.write_chronicle(state.story.chronicle)
        if activate_entry and era.entry_arc and self.fronts is not None:
            self.fronts.activate(
                state,
                era.entry_arc,
                fire_start=fire_start,
                reset_clock=False,
            )
            state.story.current_arc = era.entry_arc
            runtime = state.fronts.get(era.entry_arc)
            if runtime:
                runtime.started_day = state.day
        self.seed_player_lens(state)
        return era

    def seed_player_lens(self, state: GameState) -> None:
        """Bootstrap PC lens from location, party, and Knowledge scope links."""
        from app.wiki.wiki_query import WikiQuery

        query = WikiQuery(wiki_dir=self.wiki.wiki_dir)
        cid = state.player.resolved_character_id()
        body = ""
        meta: dict = {}
        if cid:
            card = query.load_character(cid, active_arc_ids=epoch_overlay_ids(state))
            if card:
                body = card.body or ""
                meta = dict(card.metadata or {})
            else:
                path = query.resolve_id(cid)
                if path and path.exists():
                    meta, body = query.read_page(path)
        seed_lens_impl(state, sheet_body=body, sheet_meta=meta)

    def derive_outcome(
        self,
        definition: FrontDefinition,
        runtime: FrontRuntime,
        *,
        forced: ArcOutcome | None = None,
    ) -> ArcOutcome:
        if forced:
            return forced
        if runtime.status == "interrupted":
            return "broken"
        if runtime.status == "diverted":
            return "diverted"
        if runtime.status == "resolved":
            last = (
                definition.beat_by_id.get(runtime.last_fired_beat)
                if runtime.last_fired_beat
                else None
            )
            if last and last.resolves_arc:
                kind = str(last.resolves_arc).strip().lower()
                if kind in {"weak", "canon"}:
                    return kind  # type: ignore[return-value]
                return "weak"
            if runtime.distortion_notes:
                return "diverted"
            return "canon"
        return "lapsed"

    def collect_pressures(
        self,
        definition: FrontDefinition,
        runtime: FrontRuntime,
        *,
        day: int,
    ) -> list[WorldPressure]:
        pressures: list[WorldPressure] = []
        for item in definition.intents_layer3:
            if not isinstance(item, dict):
                continue
            intent_id = str(item.get("id") or "").strip()
            if not intent_id:
                continue
            satisfied = bool(
                runtime.flags.get(f"intent_{intent_id}_satisfied", False)
            )
            if satisfied:
                continue
            entities = item.get("entities") or []
            if not isinstance(entities, list):
                entities = []
            pressures.append(
                WorldPressure(
                    id=intent_id,
                    summary=str(item.get("summary") or intent_id),
                    origin_arc=definition.id,
                    entities=[str(x) for x in entities],
                    day_opened=day,
                )
            )
        return pressures

    def apply_on_close(
        self,
        state: GameState,
        definition: FrontDefinition,
        outcome: ArcOutcome,
    ) -> list[ChronicleEntry]:
        effect = (definition.on_close or {}).get(outcome)
        if not effect:
            return []
        for key, value in (effect.world_flags or {}).items():
            state.story.world_flags[str(key)] = bool(value)
            # Mirror onto active front flags if present
            for runtime in state.fronts.values():
                if runtime:
                    runtime.flags[str(key)] = bool(value)
        if effect.wiki_writes:
            self.wiki.apply_entity_patches(effect.wiki_writes)
        added: list[ChronicleEntry] = []
        for raw in effect.chronicle or []:
            if not isinstance(raw, dict):
                continue
            cid = str(raw.get("id") or "").strip()
            summary = str(raw.get("summary") or "").strip()
            if not summary:
                continue
            if not cid:
                cid = f"{definition.id}_{outcome}_{len(added)}"
            entry = ChronicleEntry(
                id=cid,
                summary=summary,
                reach=str(raw.get("reach") or "local"),  # type: ignore[arg-type]
                secret=bool(raw.get("secret", False)),
                source="played_arc",
                arc_id=definition.id,
                day=state.day,
            )
            added.append(entry)
            state.story.chronicle.append(entry)
        return added

    def on_arc_closed(
        self,
        state: GameState,
        front_id: str,
        *,
        forced_outcome: ArcOutcome | None = None,
        skip_advance: bool = False,
    ) -> ArcRecord | None:
        runtime = state.fronts.get(front_id)
        if not runtime:
            return None
        # Avoid double-close
        if any(r.arc_id == front_id for r in state.story.arcs):
            # Allow re-close only if last record differs? Prefer idempotent skip.
            return None
        try:
            definition = self.front_loader.load(front_id)
        except FileNotFoundError:
            return None

        outcome = self.derive_outcome(definition, runtime, forced=forced_outcome)
        self.apply_on_close(state, definition, outcome)
        pressures = self.collect_pressures(definition, runtime, day=state.day)
        for pressure in pressures:
            if not any(p.id == pressure.id for p in state.story.pressures):
                state.story.pressures.append(pressure)

        if settings.arc_close_review and self.llm is not None:
            self._run_arc_close_review(state, definition, runtime, outcome)

        skipped: list[str] = []
        fired = set()
        if runtime.last_fired_beat:
            for beat in definition.beats:
                fired.add(beat.id)
                if beat.id == runtime.last_fired_beat:
                    break
        for beat in definition.beats:
            if beat.id not in fired:
                skipped.append(beat.id)

        started = runtime.started_day if runtime.started_day is not None else state.day
        record = ArcRecord(
            arc_id=front_id,
            outcome=outcome,
            started_day=int(started),
            closed_day=state.day,
            last_beat=runtime.last_fired_beat,
            skipped_beats=skipped,
            unresolved_intents=[p.id for p in pressures],
        )
        state.story.arcs.append(record)
        if state.story.current_arc == front_id:
            state.story.current_arc = None
        self.wiki.write_chronicle(state.story.chronicle)
        if not skip_advance:
            self.advance(state, closed_arc_id=front_id, outcome=outcome)
        return record

    def _run_arc_close_review(
        self,
        state: GameState,
        definition: FrontDefinition,
        runtime: FrontRuntime,
        outcome: ArcOutcome,
    ) -> None:
        try:
            from app.models.reviews import ArcCloseReviewResult
        except Exception:
            return
        try:
            system = self.llm.load_prompt("review_arc_close")
            import json as _json

            result = self.llm.complete_json(
                system=system,
                user=_json.dumps(
                    {
                        "arc_id": definition.id,
                        "arc_name": definition.name,
                        "outcome": outcome,
                        "last_beat": runtime.last_fired_beat,
                        "flags": dict(runtime.flags),
                        "day": state.day,
                    },
                    ensure_ascii=False,
                ),
                schema=ArcCloseReviewResult,
                model=settings.llm_model_review,
            )
        except Exception:
            return
        for line in getattr(result, "chronicle", []) or []:
            summary = str(getattr(line, "summary", "") or "").strip()
            if not summary:
                continue
            cid = str(getattr(line, "id", "") or "").strip() or f"{definition.id}_close_{len(state.story.chronicle)}"
            entry = ChronicleEntry(
                id=cid,
                summary=summary,
                reach=str(getattr(line, "reach", "local") or "local"),  # type: ignore[arg-type]
                secret=bool(getattr(line, "secret", False)),
                source="played_arc",
                arc_id=definition.id,
                day=state.day,
            )
            state.story.chronicle.append(entry)

    def world_flag(self, state: GameState, key: str) -> bool | None:
        if key in state.story.world_flags:
            return bool(state.story.world_flags[key])
        for runtime in state.fronts.values():
            if runtime and key in runtime.flags:
                return bool(runtime.flags[key])
        return None

    def flags_satisfied(self, state: GameState, required: dict[str, bool]) -> bool:
        for key, expected in required.items():
            actual = self.world_flag(state, key)
            if actual is None:
                actual = False
            if bool(actual) != bool(expected):
                return False
        return True

    def advance(
        self,
        state: GameState,
        *,
        closed_arc_id: str,
        outcome: ArcOutcome,
    ) -> str | None:
        """Activate next arc from era.arc_sequence with canon guard. Returns new arc id."""
        era = self._era(state)
        if not era or self.fronts is None:
            return None
        node = era.arc_by_id.get(closed_arc_id)
        if not node:
            return None
        for edge in node.next:
            if edge.when_outcome and outcome not in edge.when_outcome:
                continue
            if edge.requires_flags and not self.flags_satisfied(
                state, edge.requires_flags
            ):
                continue
            # Activate successor without rewinding the clock
            self.fronts.activate(
                state,
                edge.arc,
                fire_start=False,
                reset_clock=False,
                relative_to_now=True,
            )
            state.story.current_arc = edge.arc
            runtime = state.fronts.get(edge.arc)
            if runtime:
                runtime.started_day = state.day
            return edge.arc
        return None

    def check_stall(self, state: GameState) -> list[str]:
        """Auto-close stalled fronts. Returns closed front ids."""
        closed: list[str] = []
        stall_minutes = max(1, int(settings.stall_after_days)) * 1440
        for front_id, runtime in list(state.fronts.items()):
            if not runtime:
                continue
            if runtime.status in {"active", "diverted"}:
                if int(runtime.accumulated_minutes or 0) >= stall_minutes:
                    self._stall_fire_remaining(state, front_id, hydrate=False)
                    runtime.status = "resolved"
                    self.on_arc_closed(state, front_id, forced_outcome="lapsed")
                    closed.append(front_id)
            elif runtime.status == "interrupted":
                days_stuck = 0
                if runtime.interrupted_at_day is not None:
                    days_stuck = max(0, state.day - int(runtime.interrupted_at_day))
                else:
                    days_stuck = int(runtime.accumulated_minutes or 0) // 1440
                if days_stuck >= int(settings.stall_after_days):
                    self._stall_fire_remaining(state, front_id, hydrate=False)
                    runtime.status = "resolved"
                    self.on_arc_closed(state, front_id, forced_outcome="broken")
                    closed.append(front_id)
        return closed

    def _stall_fire_remaining(
        self, state: GameState, front_id: str, *, hydrate: bool
    ) -> None:
        """Fire remaining prereq-ok beats off-screen (no scene hydrate)."""
        if self.fronts is None:
            return
        runtime = state.fronts.get(front_id)
        if not runtime:
            return
        try:
            definition = self.front_loader.load(front_id)
        except FileNotFoundError:
            return
        max_due = max(
            (
                int(b.due_abs_minutes) + int(runtime.due_offset_minutes or 0)
                for b in definition.beats
            ),
            default=0,
        )
        from app.story.front_engine import day_minutes_from_abs
        from app.turn.game_clock import sync_time_label

        saved_day, saved_minutes = state.day, state.minutes
        state.day, state.minutes = day_minutes_from_abs(max_due)
        sync_time_label(state)
        was = runtime.status
        if runtime.status == "interrupted":
            runtime.status = "active"
        # Detach story so tick does not auto-record a weak/canon close
        saved_story = getattr(self.fronts, "story", None)
        self.fronts.story = None
        try:
            self.fronts.tick(
                state,
                0,
                front_ids=[front_id],
                hydrate_scene=hydrate,
            )
        finally:
            self.fronts.story = saved_story
        if was == "interrupted" and runtime.status == "active":
            runtime.status = was
        if absolute_minutes(saved_day, saved_minutes) > max_due:
            state.day, state.minutes = saved_day, saved_minutes
            sync_time_label(state)

    def build_story_slice(self, state: GameState) -> str:
        era = self._era(state)
        is_insider = player_is_insider(state, era)
        visible = filter_chronicle_for_player(
            list(state.story.chronicle),
            is_insider=is_insider,
            min_reach="local",
        )
        lines: list[str] = []
        if state.story.era:
            name = era.name if era else state.story.era
            lines.append(f"## Storia finora (era: {name})")
        else:
            lines.append("## Storia finora")
        if state.story.current_arc:
            lines.append(f"Arco corrente: {state.story.current_arc}")
        if state.story.arcs:
            closed = ", ".join(
                f"{r.arc_id} ({r.outcome})" for r in state.story.arcs[-5:]
            )
            lines.append(f"Archi chiusi: {closed}")
        if visible:
            lines.append("Cronaca nota al PG:")
            for entry in visible[-12:]:
                tag = " [segreto]" if entry.secret and is_insider else ""
                lines.append(f"  - ({entry.reach}){tag} {entry.summary}")
        if state.story.pressures:
            lines.append("Spinte del mondo (pressioni residue):")
            for p in state.story.pressures[-6:]:
                lines.append(f"  - {p.id}: {p.summary}")
        if len(lines) <= 1:
            return ""
        return "\n".join(lines)

    def next_candidates(self, state: GameState) -> list[dict[str, Any]]:
        era = self._era(state)
        if not era:
            return []
        closed_id = state.story.current_arc
        if state.story.arcs:
            closed_id = state.story.arcs[-1].arc_id
        if not closed_id:
            return []
        node = era.arc_by_id.get(closed_id)
        if not node:
            return []
        last_outcome = state.story.arcs[-1].outcome if state.story.arcs else None
        out: list[dict[str, Any]] = []
        for edge in node.next:
            ok_outcome = (
                not edge.when_outcome
                or last_outcome is None
                or last_outcome in edge.when_outcome
            )
            ok_flags = self.flags_satisfied(state, edge.requires_flags)
            out.append(
                {
                    "arc": edge.arc,
                    "when_outcome": list(edge.when_outcome),
                    "requires_flags": dict(edge.requires_flags),
                    "eligible": bool(ok_outcome and ok_flags),
                }
            )
        return out


def absolute_minutes(day: int, minutes: int) -> int:
    return max(0, int(day)) * 1440 + max(0, int(minutes) % 1440)
