from __future__ import annotations

from app.models.game_state import PlayerState
from app.services.wiki_query import WikiQuery


def _norm_token(raw: str) -> str:
    return str(raw or "").strip().lower().replace(" ", "-")


def player_presence_aliases(player: PlayerState) -> set[str]:
    """Tokens that identify the PG and must never appear in characters_active."""
    aliases = {
        "player",
        _norm_token(player.id),
        _norm_token(player.name),
        _norm_token(player.character_id),
        _norm_token(player.resolved_character_id()),
    }
    return {a for a in aliases if a}


def is_player_presence(token: str, player: PlayerState) -> bool:
    t = _norm_token(token)
    return bool(t) and t in player_presence_aliases(player)


def without_player(items: list[str] | None, player: PlayerState) -> list[str]:
    """Drop PG aliases from a presence list (order-preserving dedupe)."""
    if not items:
        return []
    out: list[str] = []
    for raw in items:
        token = str(raw or "").strip()
        if not token or is_player_presence(token, player):
            continue
        if token not in out:
            out.append(token)
    return out


def normalize_presence_list(items: list[str] | None, wiki: WikiQuery) -> list[str]:
    """Resolve presence entries to canonical wiki ids when possible.

    Unresolved role strings are kept as-is. Order-preserving dedupe.
    """
    if not items:
        return []
    out: list[str] = []
    for raw in items:
        token = str(raw or "").strip()
        if not token:
            continue
        path = wiki.resolve_id(token)
        if path is not None and path.exists():
            try:
                meta, _ = wiki.read_page(path)
                canonical = str(meta.get("id") or "").strip() or path.stem
            except Exception:
                canonical = path.stem
            out.append(canonical)
        else:
            out.append(token)
    return list(dict.fromkeys(out))
