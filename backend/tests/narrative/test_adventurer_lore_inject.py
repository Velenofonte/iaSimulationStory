"""Hybrid B: adventurer lore via topic, present, or location links."""

from pathlib import Path

from app.models import GameState, PlayerState
from app.player.knowledge import learn
from app.services.wiki_query import WikiQuery, build_world_excerpt


def _seed_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    (wiki / "locations").mkdir(parents=True)
    (wiki / "world").mkdir(parents=True)
    (wiki / "factions").mkdir(parents=True)
    (wiki / "index.md").write_text(
        "- [[e-rantel]] -> locations/e-rantel.md\n"
        "- [[adventurer]] -> world/adventurer.md\n"
        "- [[adventurers-guild]] -> factions/adventurers-guild.md\n"
        "- [[tob-forest]] -> locations/tob-forest.md\n",
        encoding="utf-8",
    )
    (wiki / "locations" / "e-rantel.md").write_text(
        "---\nid: e_rantel\nname: E-Rantel\ntype: location\n---\n\n"
        "# Descrizione\nSede della [[adventurers_guild|gilda]]. "
        "Ranghi in [[adventurer|avventuriero]].\n",
        encoding="utf-8",
    )
    (wiki / "locations" / "tob-forest.md").write_text(
        "---\nid: tob_forest\nname: Tob Forest\ntype: location\n---\n\n"
        "# Descrizione\nBosco. Nessuna gilda.\n",
        encoding="utf-8",
    )
    (wiki / "world" / "adventurer.md").write_text(
        "---\nid: adventurer\nname: Avventuriero\ntype: world\n---\n\n"
        "# Descrizione\n" + ("blabla " * 80) + "\n\n"
        "# Gerarchia\nCopper Iron Silver Gold Platinum Mithril Orichalcum Adamantite\n\n"
        "# Storia\n" + ("storia " * 40) + "\n",
        encoding="utf-8",
    )
    (wiki / "factions" / "adventurers-guild.md").write_text(
        "---\nid: adventurers_guild\nname: Adventurer's Guild\ntype: faction\n---\n\n"
        "# Descrizione\nGilda.\n",
        encoding="utf-8",
    )
    return wiki


def _ids(pages: list) -> set[str]:
    out: set[str] = set()
    for pid, meta, _body in pages:
        out.add(str(pid).lower())
        mid = str(meta.get("id") or "").lower()
        if mid:
            out.add(mid)
            out.add(mid.replace("_", "-"))
    return out


def test_location_links_pull_guild_and_ranks(tmp_path: Path) -> None:
    wiki = _seed_wiki(tmp_path)
    q = WikiQuery(wiki_dir=wiki)
    state = GameState(
        session_id="t",
        player=PlayerState(location="e-rantel"),
        characters_active=["mercante"],
    )
    # Public location links are visible once the PC has encountered those names
    # (signage / local talk); seed lens for the entities linked from e-rantel.
    for eid in ("adventurers_guild", "adventurer"):
        learn(state, eid, "seen")
    pages = q.query(game_state=state, user_message="guardo la piazza", mode="scene")
    ids = _ids(pages)
    assert "e-rantel" in ids or "e_rantel" in ids
    assert "adventurers_guild" in ids or "adventurers-guild" in ids
    assert "adventurer" in ids


def test_topic_in_forest_pulls_ranks(tmp_path: Path) -> None:
    wiki = _seed_wiki(tmp_path)
    q = WikiQuery(wiki_dir=wiki)
    state = GameState(
        session_id="t",
        player=PlayerState(location="tob-forest"),
        characters_active=["contadino"],
    )
    pages = q.query(
        game_state=state,
        user_message="Che ranghi ci sono alla gilda?",
        mode="scene",
    )
    ids = _ids(pages)
    assert "adventurer" in ids
    assert "adventurers_guild" in ids or "adventurers-guild" in ids


def test_adventurer_present_in_forest_pulls_ranks(tmp_path: Path) -> None:
    wiki = _seed_wiki(tmp_path)
    q = WikiQuery(wiki_dir=wiki)
    state = GameState(
        session_id="t",
        player=PlayerState(location="tob-forest"),
        characters_active=["Kren (avventuriero, ferro)"],
    )
    pages = q.query(game_state=state, user_message="chi sei?", mode="scene")
    ids = _ids(pages)
    assert "adventurer" in ids


def test_peasant_forest_idle_no_ranks(tmp_path: Path) -> None:
    wiki = _seed_wiki(tmp_path)
    q = WikiQuery(wiki_dir=wiki)
    state = GameState(
        session_id="t",
        player=PlayerState(location="tob-forest"),
        characters_active=["contadino del villaggio"],
    )
    pages = q.query(game_state=state, user_message="che tempo fa?", mode="scene")
    ids = _ids(pages)
    assert "adventurer" not in ids
    assert "adventurers_guild" not in ids


def test_build_world_excerpt_prefers_gerarchia() -> None:
    body = (
        "# Descrizione\n" + ("x" * 600) + "\n\n"
        "# Gerarchia\nCopper Iron Silver Gold Platinum Mithril Orichalcum Adamantite\n\n"
        "# Storia\n" + ("y" * 200) + "\n"
    )
    # Cap corto: senza preferenza la Gerarchia resterebbe fuori
    naive = body.replace("\n", " ")[:500]
    assert "Mithril" not in naive
    excerpt = build_world_excerpt(body, 500, entity_id="adventurer")
    assert "Mithril" in excerpt
    assert "Adamantite" in excerpt
    assert "Gerarchia" in excerpt[:80]
