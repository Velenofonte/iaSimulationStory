"""Derive and enforce pending narrative threads in situations."""

from __future__ import annotations

import re

from app.models.game_state import GameState, NpcKnowledgeFact, slugify_fact_id
from app.models.narrative import Episode
from app.models.turn import TurnResolution

SITUATIONS_CAP = 6
_BRIEF_MAX = 280
_JOIN_BRIEF_MAX = 160

_EXIT_RE = re.compile(
    r"\b(?:vado|parto|partiamo|mi\s+incammino|me\s+ne\s+vado|lascio|abbandono)\b",
    re.IGNORECASE,
)
_OPENING_HINT_RE = re.compile(
    r"\b(?:medaglione|messaggio|mistero|oggetto|figura|creatura|prigionier|"
    r"minaccia|patto|accordo|incarico|consegna)\w*\b",
    re.IGNORECASE,
)


def _clip(text: str, max_len: int) -> str:
    """Trim at a word boundary so sidebar text is not cut mid-sentence."""
    raw = (text or "").strip()
    if len(raw) <= max_len:
        return raw
    cut = raw[: max_len - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;:—- ") + "…"


def _stable_id(*parts: str) -> str:
    joined = "_".join(p.strip() for p in parts if (p or "").strip())
    return slugify_fact_id(joined, max_len=56) or "thread"


def derive_situations(
    resolution: TurnResolution,
    episode: Episode | None,
    state: GameState,
) -> list[NpcKnowledgeFact]:
    """Build situations_add when the model left openings untracked."""
    out: list[NpcKnowledgeFact] = []
    loc = state.player.location or "qui"
    existing_ids = {s.id for s in state.situations}

    if episode is not None and int(episode.tier) >= 2 and getattr(episode, "opens_thread", True):
        label = (episode.tier_label or f"T{episode.tier}").strip()
        kind = (episode.kind or "evento").strip()
        fid = _stable_id("episode", kind, loc)
        # Reuse existing episode thread at this location if present.
        for sit in state.situations:
            if sit.id.startswith(f"episode_{slugify_fact_id(kind)}") or sit.id == fid:
                fid = sit.id
                break
        out.append(NpcKnowledgeFact(id=fid, summary=f"{kind} a {loc}: {label}"))

    for cid in resolution.present_join or []:
        cid = str(cid or "").strip()
        if not cid:
            continue
        brief = ""
        if resolution.scene_brief:
            brief = _clip(str(resolution.scene_brief[0]), _JOIN_BRIEF_MAX)
        fid = _stable_id("present", cid)
        summary = f"{cid} in scena" + (f" — {brief}" if brief else "")
        out.append(NpcKnowledgeFact(id=fid, summary=summary))

    if not out and resolution.scene_brief:
        for bullet in resolution.scene_brief:
            text = str(bullet or "").strip()
            if text and _OPENING_HINT_RE.search(text):
                clipped = _clip(text, _BRIEF_MAX)
                fid = _stable_id("brief", clipped)
                # Prefer updating an existing situation with overlapping summary.
                for sit in state.situations:
                    if sit.summary.casefold()[:40] == clipped.casefold()[:40]:
                        fid = sit.id
                        break
                out.append(NpcKnowledgeFact(id=fid, summary=clipped))
                break

    unique: list[NpcKnowledgeFact] = []
    seen = set(existing_ids)
    for item in out:
        # Always allow upsert of existing id (summary refresh).
        if item.id in seen and item.id not in existing_ids:
            continue
        if item.id not in existing_ids:
            # Skip brand-new duplicate summaries.
            if any(
                s.summary.strip().casefold() == item.summary.strip().casefold()
                for s in state.situations
            ):
                continue
        seen.add(item.id)
        unique.append(item)
    return unique


def ensure_pending_threads(
    resolution: TurnResolution,
    episode: Episode | None,
    state: GameState,
) -> TurnResolution:
    """If openings left situations_add empty, derive them in code."""
    if resolution.situations_add:
        return _cap_situations(resolution, state)
    derived = derive_situations(resolution, episode, state)
    if not derived:
        return resolution
    updated = resolution.model_copy(update={"situations_add": derived})
    return _cap_situations(updated, state)


def _cap_situations(resolution: TurnResolution, state: GameState) -> TurnResolution:
    """One-in-one-out: at cap, drop oldest existing via situations_remove (by id)."""
    adds = list(resolution.situations_add or [])
    removes = list(resolution.situations_remove or [])
    remove_set = set(removes)
    current = [s for s in state.situations if s.id not in remove_set]
    projected_ids = [s.id for s in current]
    add_ids = [a.id for a in adds]
    for aid in add_ids:
        if aid not in projected_ids:
            projected_ids.append(aid)
    overflow = len(projected_ids) - SITUATIONS_CAP
    if overflow <= 0:
        return resolution
    drop: list[str] = []
    add_id_set = set(add_ids)
    for sit in current:
        if overflow <= 0:
            break
        if sit.id in add_id_set:
            continue
        drop.append(sit.id)
        overflow -= 1
    if not drop:
        return resolution
    return resolution.model_copy(
        update={"situations_remove": list(dict.fromkeys(removes + drop))}
    )


def is_exit_intent(player_action: str, *, location_changed: bool) -> bool:
    if location_changed:
        return True
    return bool(_EXIT_RE.search(player_action or ""))


def ensure_exit_threads(
    resolution: TurnResolution,
    *,
    player_action: str,
    previous_location: str,
    state: GameState,
) -> TurnResolution:
    """Leaving a scene with open threads must update situations (same ids)."""
    loc_changed = bool(
        resolution.location
        and str(resolution.location).strip()
        and str(resolution.location).strip() != (previous_location or "").strip()
    )
    if not is_exit_intent(player_action, location_changed=loc_changed):
        return resolution
    if not state.situations:
        return resolution
    touched = bool(resolution.situations_add or resolution.situations_remove)
    if touched:
        return resolution
    # Defer open threads in place: same id, summary prefixed.
    deferred = [
        NpcKnowledgeFact(
            id=sit.id,
            summary=f"In sospeso lasciando {previous_location or 'la scena'}: {sit.summary}",
        )
        for sit in state.situations[:SITUATIONS_CAP]
    ]
    return resolution.model_copy(
        update={
            "situations_add": deferred,
            "situations_remove": [],
        }
    )
