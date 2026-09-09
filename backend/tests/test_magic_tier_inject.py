"""Inject magic-tier world page when player casts with []."""

from pathlib import Path

from app.models import GameState, PlayerState
from app.services.wiki_query import WikiQuery, build_world_excerpt


def _seed(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    (wiki / "locations").mkdir(parents=True)
    (wiki / "world").mkdir(parents=True)
    (wiki / "index.md").write_text(
        "- [[e-rantel]] -> locations/e-rantel.md\n"
        "- [[magic-tier]] -> world/magic-tier.md\n",
        encoding="utf-8",
    )
    (wiki / "locations" / "e-rantel.md").write_text(
        "---\nid: e_rantel\nname: E-Rantel\ntype: location\n---\n\n# Descrizione\nCitta.\n",
        encoding="utf-8",
    )
    (wiki / "world" / "magic-tier.md").write_text(
        "---\nid: tier_magic\nname: Tier Magic\ntype: world\n---\n\n"
        "# Descrizione\n" + ("x" * 400) + "\n\n"
        "# Scala dei tier\n"
        "0° 1° 2° 3° 4° 5° 6° 7° 8° 9° 10° Super-Tier\n",
        encoding="utf-8",
    )
    return wiki


def test_spell_cast_injects_magic_tier(tmp_path: Path) -> None:
    wiki = _seed(tmp_path)
    q = WikiQuery(wiki_dir=wiki)
    state = GameState(
        session_id="t",
        player=PlayerState(location="e-rantel"),
    )
    pages = q.query(
        game_state=state,
        user_message='Lancio [Fireball — palla di fuoco di 3rd tier]',
        mode="scene",
    )
    ids = {pid.lower() for pid, _, _ in pages}
    assert "magic-tier" in ids or "tier_magic" in ids


def test_wiki_link_does_not_inject_magic_tier(tmp_path: Path) -> None:
    wiki = _seed(tmp_path)
    q = WikiQuery(wiki_dir=wiki)
    state = GameState(
        session_id="t",
        player=PlayerState(location="e-rantel"),
    )
    pages = q.query(
        game_state=state,
        user_message="Guardo [[magic-tier]] sulla bacheca.",
        mode="scene",
    )
    ids = {pid.lower() for pid, _, _ in pages}
    # Il link wiki non e' un cast; non forzare inject (puo' entrare solo se resolve dal testo)
    assert not q.should_include_magic_tier_lore(
        user_message="Guardo [[magic-tier]] sulla bacheca."
    )


def test_idle_message_no_magic_tier(tmp_path: Path) -> None:
    wiki = _seed(tmp_path)
    q = WikiQuery(wiki_dir=wiki)
    state = GameState(
        session_id="t",
        player=PlayerState(location="e-rantel"),
    )
    pages = q.query(game_state=state, user_message="saluto la receptionist", mode="scene")
    ids = {pid.lower() for pid, _, _ in pages}
    assert "magic-tier" not in ids
    assert "tier_magic" not in ids


def test_excerpt_prefers_scala_dei_tier() -> None:
    body = (
        "# Descrizione\n" + ("x" * 600) + "\n\n"
        "# Scala dei tier\n0° 1° 3° 10° Super-Tier\n"
    )
    assert "Super-Tier" not in body.replace("\n", " ")[:500]
    excerpt = build_world_excerpt(body, 500, entity_id="magic-tier")
    assert "Super-Tier" in excerpt
    assert "Scala dei tier" in excerpt[:80]
