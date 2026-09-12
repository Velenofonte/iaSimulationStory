"""Ambient episode director: contextual roll for openings (agnostic of setting lore)."""

from __future__ import annotations

import hashlib
import random
from typing import Any

from app.config import settings
from app.models.game_state import GameState
from app.models.narrative import Episode
from app.services.episode_pack import EpisodePack, load_episode_pack
from app.services.notoriety import gap as notoriety_gap

_TIER_COUNT = 7
_RECENT_KIND_PENALTY = 0.35
_RECENT_KIND_BAR = 2
_PILEUP_LIMIT = 2
_HIGH_NOTORIETY_SCORE = 40.0
_HIGH_GAP = 2


def _seed_rng(session_id: str, turn_index: int, salt: str = "") -> random.Random:
    material = f"{salt}:{session_id}:{turn_index}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _mul(a: list[float], b: list[float]) -> list[float]:
    n = min(len(a), len(b), _TIER_COUNT)
    out = [a[i] * b[i] for i in range(n)]
    while len(out) < _TIER_COUNT:
        out.append(0.0)
    return out


def _apply_tier_policy(weights: list[float]) -> list[float]:
    """T1 (segno) is never sampled — zero slot 1 and keep a 7-vector."""
    out = list(weights[:_TIER_COUNT])
    while len(out) < _TIER_COUNT:
        out.append(0.0)
    out[1] = 0.0
    return out


def _normalize(weights: list[float]) -> list[float]:
    cleaned = _apply_tier_policy([max(0.0, float(w)) for w in weights[:_TIER_COUNT]])
    total = sum(cleaned)
    if total <= 0:
        cleaned[0] = 1.0
        return cleaned
    return [w / total for w in cleaned]


def _sample(rng: random.Random, weights: list[float]) -> int:
    probs = _normalize(weights)
    roll = rng.random()
    acc = 0.0
    for i, p in enumerate(probs):
        acc += p
        if roll <= acc:
            return i
    return len(probs) - 1


def _is_night(state: GameState) -> bool:
    label = (state.time or "").lower()
    if "notte" in label or "sera" in label:
        return True
    # Fallback on clock minutes if label missing.
    minutes = int(state.minutes or 0) % 1440
    return minutes >= 20 * 60 or minutes < 5 * 60


def _is_indoor(location_kind: str) -> bool:
    return location_kind in {"inn", "settlement"}


def _cooldown_turns(last_tier: int) -> int:
    # Every tier needs a quiet turn before the next roll, or a light sign lands on
    # each beat and keeps re-opening the same motif. Heavier episodes rest longer.
    tier = max(0, int(last_tier))
    if tier <= 0:
        return 0
    if tier <= 2:
        return 1
    if tier <= 4:
        return 2
    return max(2, int(settings.episode_cooldown_turns or 0))


def _danger_shift(weights: list[float], danger: str | None) -> list[float]:
    key = (danger or "").strip().lower()
    if key in {"high", "alta", "alto"}:
        return _mul(weights, [0.7, 0.0, 1.0, 1.1, 1.2, 1.4, 1.3])
    if key in {"low", "bassa", "basso"}:
        return _mul(weights, [1.3, 0.0, 1.1, 0.9, 0.7, 0.5, 0.4])
    return weights


def has_pending_thread(state: GameState) -> bool:
    """True when open situations should block new episodic openings."""
    return bool(state.situations)


class EpisodeDirector:
    def __init__(self, pack: EpisodePack | None = None) -> None:
        self.pack = pack

    def _pack_for(self, state: GameState) -> EpisodePack:
        if self.pack is not None:
            return self.pack
        return load_episode_pack(state.story_id)

    def decide(
        self,
        state: GameState,
        *,
        stance: str = "action",
        location_meta: dict[str, Any] | None = None,
        beat_imminent: bool = False,
    ) -> Episode | None:
        if not settings.episode_engine_enabled:
            return None

        pack = self._pack_for(state)
        meta = location_meta or {}
        location_kind = str(meta.get("kind") or "default").strip().lower() or "default"
        danger = meta.get("danger")
        runtime = state.episode
        turn_index = int(runtime.turn_index)

        # Hard suppress when a front beat is due / just fired.
        if beat_imminent:
            return None
        if runtime.last_beat_turn is not None and turn_index - int(runtime.last_beat_turn) <= 1:
            return None
        # Pile-up guard: openings must not stack faster than the scene resolves them.
        if int(runtime.consecutive_events) >= _PILEUP_LIMIT:
            return None
        # Pending-thread gate: no new T2+ while a narrative debt is open.
        pending = has_pending_thread(state)
        if pending:
            return None

        rng = _seed_rng(
            state.session_id,
            turn_index,
            salt=settings.episode_seed_salt or "",
        )

        weights = pack.location_profile(location_kind)
        weights = _danger_shift(weights, str(danger) if danger is not None else None)

        # Slightly more silence when there is no open debt.
        calm = pack.modifier("baseline_calm")
        if calm:
            weights = _mul(weights, calm)

        if _is_night(state):
            mod = pack.modifier("night")
            if mod:
                weights = _mul(weights, mod)
        if not state.characters_active:
            mod = pack.modifier("alone")
            if mod:
                weights = _mul(weights, mod)
        if _is_indoor(location_kind):
            mod = pack.modifier("indoor")
            if mod:
                weights = _mul(weights, mod)

        stance_key = (stance or "action").strip().lower()
        if stance_key == "wait":
            # A second wait in a row asks for the pending thread to move, not for a
            # fresh element: push hard toward "nothing new" so the resolver must
            # advance what the player is actually waiting on.
            repeated = (runtime.last_stance or "") == "wait"
            mod = pack.modifier("stance_wait_repeat" if repeated else "stance_wait")
            if mod:
                weights = _mul(weights, mod)
        elif stance_key == "dialogue":
            mod = pack.modifier("stance_dialogue")
            if mod:
                weights = _mul(weights, mod)

        cooldown = _cooldown_turns(runtime.last_tier)
        if runtime.turns_since_event < cooldown:
            mod = pack.modifier("cooldown")
            if mod:
                weights = _mul(weights, mod)

        # Quiet streak ramp only when there is no open debt (debt already gated above).
        quiet = max(0, int(runtime.turns_since_event))
        ramp = float(settings.episode_quiet_ramp or 1.0)
        quiet_mod = pack.modifier("quiet_streak")
        if quiet_mod and quiet > 0 and ramp > 0:
            for _ in range(min(quiet, 8)):
                scaled = [1.0 + (w - 1.0) * ramp for w in quiet_mod]
                weights = _mul(weights, scaled)

        # No consecutive T5/T6.
        if runtime.last_tier >= 5 and runtime.turns_since_event == 0:
            weights[5] = 0.0
            weights[6] = 0.0

        weights = _apply_tier_policy(weights)
        tier = _sample(rng, weights)
        if tier <= 0 or tier == 1:
            return None

        kind = self._pick_kind(
            rng,
            pack,
            tier=tier,
            location_kind=location_kind,
            state=state,
        )
        exposure, witnesses = self._exposure(pack, state, location_kind)

        return Episode(
            tier=tier,
            tier_label=pack.tier_label(tier),
            kind=kind,
            exposure=exposure,
            witnesses=witnesses,
            no_auto_damage=True,
            must_not_resolve=True,
            opens_thread=tier >= 2,
        )

    def _pick_kind(
        self,
        rng: random.Random,
        pack: EpisodePack,
        *,
        tier: int,
        location_kind: str,
        state: GameState,
    ) -> str:
        candidates: list[tuple[str, float]] = []
        recent = list(state.episode.recent_kinds or [])
        for kind, spec in pack.kinds.items():
            allowed = [int(x) for x in (spec.get("tiers") or [])]
            if tier not in allowed:
                continue
            by_loc = spec.get("by_location") or {}
            weight = float(by_loc.get(location_kind, by_loc.get("default", 1.0)))
            if kind in recent:
                # Steps back from the newest entry: the last two kinds are barred so a
                # motif cannot return every other turn; older ones recover linearly.
                newest = max(i for i, used in enumerate(recent) if used == kind)
                steps = len(recent) - 1 - newest
                if steps < _RECENT_KIND_BAR:
                    weight = 0.0
                else:
                    weight *= min(1.0, _RECENT_KIND_PENALTY * (steps - _RECENT_KIND_BAR + 1))
            candidates.append((kind, weight))

        candidates = self._apply_notoriety_kind_weights(candidates, pack, state)

        if not candidates:
            return "mystery"
        total = sum(max(0.0, w) for _, w in candidates)
        if total <= 0:
            return candidates[0][0]
        roll = rng.random() * total
        acc = 0.0
        for kind, weight in candidates:
            acc += max(0.0, weight)
            if roll <= acc:
                return kind
        return candidates[-1][0]

    def _apply_notoriety_kind_weights(
        self,
        candidates: list[tuple[str, float]],
        pack: EpisodePack,
        state: GameState,
    ) -> list[tuple[str, float]]:
        bands = pack.notoriety_kind_weights or {}
        score = float(state.notoriety.score or 0.0)
        if score >= _HIGH_NOTORIETY_SCORE:
            table = bands.get("high") or {}
        else:
            table = bands.get("low") or {}
        gap_val = notoriety_gap(state, pack)
        gap_table = bands.get("gap_high") or {} if gap_val >= _HIGH_GAP else {}

        out: list[tuple[str, float]] = []
        for kind, weight in candidates:
            w = weight * float(table.get(kind, 1.0))
            if gap_table:
                w *= float(gap_table.get(kind, 1.0))
            out.append((kind, w))
        return out

    def _exposure(
        self,
        pack: EpisodePack,
        state: GameState,
        location_kind: str,
    ) -> tuple[str, list[str]]:
        present = list(state.characters_active or [])
        witnesses: list[str] = []
        reach_map = (pack.exposure.get("witness_reach") or {}) if pack.exposure else {}
        thresholds = (pack.exposure.get("thresholds") or {}) if pack.exposure else {}

        # Map present NPC ids to coarse roles when possible; otherwise "civilian".
        for cid in present:
            role = "civilian"
            lower = cid.lower()
            for key in reach_map:
                if key in lower:
                    role = key
                    break
            witnesses.append(role)

        if not witnesses and location_kind in {"inn", "settlement"}:
            # Crowded places imply ambient witnesses even if not named in present.
            witnesses = ["civilian"]

        score = 0
        for role in witnesses:
            reach = str(reach_map.get(role, "local"))
            score += 1 + pack.reach_index(reach)

        low = float(thresholds.get("low", 0))
        mid = float(thresholds.get("medium", 2))
        high = float(thresholds.get("high", 5))
        if score >= high:
            level = "high"
        elif score >= mid:
            level = "medium"
        elif score >= low and witnesses:
            level = "low"
        else:
            level = "low" if witnesses else "low"
            if not witnesses:
                level = "low"

        # Deduplicate roles preserving order.
        witnesses = list(dict.fromkeys(witnesses))
        return level, witnesses

    @staticmethod
    def record_outcome(
        state: GameState,
        episode: Episode | None,
        *,
        stance: str = "action",
        beat_fired: bool = False,
    ) -> None:
        runtime = state.episode
        runtime.turn_index = int(runtime.turn_index) + 1
        runtime.last_stance = (stance or "action").strip().lower()
        if beat_fired:
            runtime.last_beat_turn = runtime.turn_index
        if episode is None or episode.tier <= 0:
            runtime.turns_since_event = int(runtime.turns_since_event) + 1
            runtime.consecutive_events = 0
            return
        runtime.turns_since_event = 0
        runtime.consecutive_events = int(runtime.consecutive_events) + 1
        runtime.last_tier = int(episode.tier)
        kinds = list(runtime.recent_kinds or [])
        if episode.kind:
            kinds.append(episode.kind)
        runtime.recent_kinds = kinds[-5:]
