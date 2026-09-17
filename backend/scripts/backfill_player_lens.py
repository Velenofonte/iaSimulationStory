"""Backfill PlayerState.lens.named from prior chat for an existing session.

Usage (from backend/):
  PYTHONPATH=. python scripts/backfill_player_lens.py [session_id]

If session_id is omitted, uses the active session.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.player_lens import backfill_from_chat, known_ids, seed_player_lens
from app.services.save_manager import SaveManager
from app.services.wiki_query import WikiQuery


def _candidate_ids(wiki: WikiQuery) -> list[str]:
    ids = sorted(wiki.index.keys())
    # Also scan character filenames as fallback.
    chars = wiki.wiki_dir / "characters"
    if chars.is_dir():
        for path in chars.glob("*.md"):
            ids.append(path.stem.lower())
    locs = wiki.wiki_dir / "locations"
    if locs.is_dir():
        for path in locs.rglob("*.md"):
            ids.append(path.stem.lower())
    return list(dict.fromkeys(ids))


def main(session_id: str | None = None) -> None:
    saves = SaveManager()
    sid = (session_id or "").strip() or saves.get_active_session_id()
    if not sid:
        raise SystemExit("No session_id and no active session")
    state = saves.load_game_state(sid)
    if state is None:
        raise SystemExit(f"Missing game_state for {sid}")

    wiki = WikiQuery(wiki_dir=saves.wiki_dir(sid))
    card = wiki.load_character(state.player.resolved_character_id())
    seed_player_lens(
        state,
        sheet_body=(card.body if card else ""),
        sheet_meta=(dict(card.metadata) if card else {}),
    )

    messages = saves.load_all_chat(sid)
    texts = [m.content for m in messages if getattr(m, "content", None)]
    learned = backfill_from_chat(
        state,
        texts,
        candidate_ids=_candidate_ids(wiki),
    )
    saves.save_game_state(state)
    print(f"session={sid}")
    print(f"named={known_ids(state, min_level='named')}")
    print(f"newly_named_from_chat={learned}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
