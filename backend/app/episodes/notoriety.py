"""Notoriety: how the world reads the player from structured deeds (setting-agnostic)."""

from __future__ import annotations

from app.models.game_state import DeedRecord, GameState, NotorietyRuntime
from app.episodes.episode_pack import EpisodePack, load_episode_pack


def _pack(state: GameState, pack: EpisodePack | None) -> EpisodePack:
    return pack if pack is not None else load_episode_pack(state.story_id)


def apply_deed(
    state: GameState,
    deed: DeedRecord,
    pack: EpisodePack | None = None,
) -> None:
    """Apply a structured deed to notoriety runtime."""
    p = _pack(state, pack)
    runtime = state.notoriety
    weight = p.scale_weight(deed.scale)
    if weight <= 0:
        weight = 1.0

    witness_bonus = 0.0
    reaches: list[str] = []
    reach_map = (p.exposure.get("witness_reach") or {}) if p.exposure else {}
    for role in deed.witnesses or []:
        reach = str(reach_map.get(str(role).lower(), "local"))
        reaches.append(reach)
        witness_bonus += 1.0 + 0.5 * p.reach_index(reach)

    beneficiary = (deed.beneficiary or "none").strip().lower() or "none"
    ben_reach = p.beneficiary_reach.get(beneficiary, "none")
    reaches.append(ben_reach)
    beneficiary_mult = 1.0 + 0.35 * p.reach_index(ben_reach)

    total = weight * max(1.0, witness_bonus) * beneficiary_mult
    if deed.evidence and str(deed.evidence).strip().lower() not in {"", "none", "false"}:
        total *= 1.25
        deed.persistent = True

    if deed.day is None:
        deed.day = state.day

    # Upsert by id.
    by_id = {d.id: d for d in runtime.deeds}
    by_id[deed.id] = deed
    runtime.deeds = list(by_id.values())[-40:]

    if deed.attributed:
        runtime.score = float(runtime.score) + total
    else:
        runtime.legend_score = float(runtime.legend_score) + total

    runtime.reach = p.max_reach([runtime.reach, *reaches])


def decay(state: GameState, pack: EpisodePack | None = None, *, days: float = 1.0) -> None:
    """Decay scores; persistent-evidence deeds are exempt from legend/score decay portion."""
    if days <= 0:
        return
    p = _pack(state, pack)
    runtime = state.notoriety
    score_rate = float(p.decay.get("score_per_day") or 0.0)
    legend_rate = float(p.decay.get("legend_per_day") or 0.0)
    exempt = bool(p.decay.get("persistent_evidence_exempt", True))

    has_persistent = any(d.persistent for d in runtime.deeds)
    if not (exempt and has_persistent):
        runtime.score = max(0.0, float(runtime.score) - score_rate * days)
        runtime.legend_score = max(0.0, float(runtime.legend_score) - legend_rate * days)
    else:
        # Soft decay only on non-persistent portion (half rate).
        runtime.score = max(0.0, float(runtime.score) - score_rate * days * 0.25)
        runtime.legend_score = max(0.0, float(runtime.legend_score) - legend_rate * days * 0.25)


def implied_band_rank(state: GameState, pack: EpisodePack | None = None) -> int:
    """Map current score to the highest scale band whose weight is below the score."""
    p = _pack(state, pack)
    score = float(state.notoriety.score or 0.0)
    best = 0
    for band, meta in p.scale_bands.items():
        try:
            w = float(meta.get("weight") or 0)
            rank = int(meta.get("expected_label_rank") or 0)
        except (TypeError, ValueError):
            continue
        if score >= w:
            best = max(best, rank)
    return best


def label_rank(state: GameState, pack: EpisodePack | None = None) -> int:
    p = _pack(state, pack)
    ranks = [p.label_rank(lbl) for lbl in state.notoriety.labels]
    ranks = [r for r in ranks if r is not None]
    return max(ranks) if ranks else 0


def gap(state: GameState, pack: EpisodePack | None = None) -> int:
    """Positive when deeds outrank formal labels (incoherence the world notices)."""
    return max(0, implied_band_rank(state, pack) - label_rank(state, pack))


def to_prompt_slice(state: GameState, pack: EpisodePack | None = None) -> str:
    """Compact notoriety block for NarrativeRequest (no setting-specific prose)."""
    p = _pack(state, pack)
    runtime = state.notoriety
    if (
        runtime.score <= 0
        and runtime.legend_score <= 0
        and not runtime.labels
        and not runtime.deeds
    ):
        return ""

    lines = [
        "## Notorieta (stato mondo, neutro)",
        f"score={runtime.score:.1f}",
        f"legend_score={runtime.legend_score:.1f}",
        f"reach={runtime.reach}",
        f"gap={gap(state, p)}",
    ]
    if runtime.labels:
        lines.append("labels=" + ", ".join(runtime.labels))
    if runtime.attribution:
        attrs = ", ".join(f"{k}:{v:.1f}" for k, v in list(runtime.attribution.items())[:6])
        lines.append(f"attribution={attrs}")
    if runtime.deeds:
        recent = runtime.deeds[-3:]
        for deed in recent:
            flag = "attributed" if deed.attributed else "unattributed"
            lines.append(
                f"- deed {deed.id} scale={deed.scale} {flag}: {deed.summary[:120]}"
            )
    lines.append(
        "Usa questi fatti solo come contesto di mondo; non spingere una strategia "
        "(nascondersi o rivelarsi) sul PG."
    )
    return "\n".join(lines)


def format_wiki_section(state: GameState, pack: EpisodePack | None = None) -> list[str]:
    """Bullet lines for the runtime-only # Notorieta wiki section."""
    runtime = state.notoriety
    lines: list[str] = []
    if runtime.labels:
        lines.append("Etichette: " + ", ".join(runtime.labels))
    lines.append(f"Portata: {runtime.reach}")
    lines.append(f"Score: {runtime.score:.1f} (leggenda: {runtime.legend_score:.1f})")
    g = gap(state, pack)
    if g:
        lines.append(f"Scarto imprese/etichetta: {g}")
    if runtime.attribution:
        for key, val in list(runtime.attribution.items())[:8]:
            lines.append(f"Attribuzione {key}: {val:.1f}")
    for deed in runtime.deeds[-8:]:
        tag = "" if deed.attributed else " [non attribuita]"
        lines.append(f"Impresa ({deed.scale}){tag}: {deed.summary}")
    return lines


def ensure_runtime(state: GameState) -> NotorietyRuntime:
    if state.notoriety is None:  # type: ignore[truthy-bool]
        state.notoriety = NotorietyRuntime()
    return state.notoriety
