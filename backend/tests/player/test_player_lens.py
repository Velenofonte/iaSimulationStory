"""Tests for player-character epistemic lens (outbound gate)."""

from __future__ import annotations

from pathlib import Path

from app.models import CharacterCard, GameState, OffscreenCharacter, PlayerState
from app.models.turn import FrontOutcome, SceneStateDelta
from app.services.player_lens import (
    apply_turn_learning,
    is_named,
    known_ids,
    label,
    learn,
    level,
    seed_player_lens,
)
from app.services.prompt_builder import PromptBuilder
from app.services.state_reducer import apply_front_outcome, apply_scene_delta, format_offscreen_lines
from app.services.wiki_query import WikiQuery


def test_learn_place_on_arrival() -> None:
    state = GameState(session_id="s", player=PlayerState(location="e-rantel"))
    apply_turn_learning(state, previous_location="e-rantel")
    assert is_named(state, "e-rantel")

    apply_scene_delta(
        state, SceneStateDelta(player_location="great-wall", characters_active=[])
    )
    apply_turn_learning(state, previous_location="e-rantel")
    assert is_named(state, "great-wall")
    assert level(state, "e-rantel") == "named"


def test_nearby_stays_unseen_named_until_dialogue() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(location="great-wall"),
        characters_offscreen={
            "pabel": OffscreenCharacter(where="great-wall", reason="nearby"),
        },
    )
    apply_front_outcome(
        state,
        FrontOutcome(characters_nearby={"pabel": "great-wall"}),
    )
    assert level(state, "pabel") is None

    apply_scene_delta(state, SceneStateDelta(present_join=["pabel"]))
    apply_turn_learning(state, message="guardo il sergente")
    assert level(state, "pabel") == "seen"
    assert not is_named(state, "pabel")

    apply_turn_learning(state, message='Dico: "Chi comanda qui?"')
    assert is_named(state, "pabel")


def test_player_names_entity_marks_named() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(location="great-wall"),
        characters_offscreen={
            "orlando": OffscreenCharacter(where="great-wall", reason="nearby"),
        },
    )
    apply_turn_learning(
        state,
        message='Urlo: "Orlando!"',
        message_entity_ids=["orlando"],
    )
    assert is_named(state, "orlando")


def test_cast_acting_introduces_named() -> None:
    state = GameState(session_id="s", player=PlayerState(location="village"))
    apply_front_outcome(
        state,
        FrontOutcome(characters_add=["hero"]),
    )
    assert is_named(state, "hero")
    assert "hero" in state.characters_active


def test_format_offscreen_masks_unknown_name() -> None:
    state = GameState(
        session_id="s",
        characters_offscreen={
            "pabel": OffscreenCharacter(where="great-wall", reason="nearby"),
            "known": OffscreenCharacter(where="gate", reason="duty"),
        },
    )
    learn(state, "known", "named")
    lines = format_offscreen_lines(state, roles={"pabel": "sergente"})
    assert any("NARRATOR_ONLY" in line and "sergente" in line for line in lines)
    assert any(line.startswith("known") for line in lines)
    assert not any(line.startswith("pabel —") for line in lines)


def test_prompt_card_masks_seen_name() -> None:
    card = CharacterCard(
        id="pabel",
        name="Pabel Baraja",
        tier="canonical",
        role="sergente",
        body="# Aspetto fisico\nAlto.\n",
        metadata={},
    )
    text = PromptBuilder().build_prompt_card(
        card, {}, lens_level="seen", visible_role="sergente"
    )
    assert "Nome visibile al PG: sergente" in text
    assert "Nome vero (NARRATOR_ONLY): Pabel Baraja" in text
    assert "Nome: Pabel" not in text.split("\n")[1]


def test_seed_from_knowledge_scope() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(name="Rayan", location="carne", character_id="rayan"),
    )
    body = "# Knowledge scope\nSa di [[enri]] e del [[tob-forest]].\n\n# Memorie\n-\n"
    seed_player_lens(
        state,
        sheet_body=body,
        sheet_meta={"residence": "[[carne]]", "affiliation": "villaggio"},
    )
    assert is_named(state, "carne")
    assert is_named(state, "enri")
    assert is_named(state, "tob-forest")
    assert is_named(state, "rayan")
    assert "enri" in known_ids(state, min_level="named")


def test_wiki_query_filters_unknown_linked_characters(tmp_path: Path) -> None:
    wiki_dir = tmp_path / "wiki"
    (wiki_dir / "locations").mkdir(parents=True)
    (wiki_dir / "characters").mkdir(parents=True)
    loc = wiki_dir / "locations" / "kalinsha.md"
    loc.write_text(
        "---\nid: kalinsha\nname: Kalinsha\ntype: location\n---\n"
        "Capitale. [[calca]] e [[remedios]] sono a corte.\n",
        encoding="utf-8",
    )
    for cid, name in (("calca", "Calca"), ("remedios", "Remedios")):
        (wiki_dir / "characters" / f"{cid}.md").write_text(
            f"---\nid: {cid}\nname: {name}\ntype: character\n---\n# Aspetto fisico\n.\n",
            encoding="utf-8",
        )
    (wiki_dir / "index.md").write_text(
        "[[kalinsha]] -> locations/kalinsha.md\n"
        "[[calca]] -> characters/calca.md\n"
        "[[remedios]] -> characters/remedios.md\n",
        encoding="utf-8",
    )
    query = WikiQuery(wiki_dir=wiki_dir)
    state = GameState(
        session_id="s",
        player=PlayerState(location="kalinsha"),
    )
    learn(state, "kalinsha", "named")

    pages = query.query(game_state=state, user_message="guardo intorno", mode="scene")
    ids = {p[0] for p in pages}
    assert "kalinsha" in ids
    assert "calca" not in ids
    assert "remedios" not in ids

    pages2 = query.query(
        game_state=state, user_message="Chiedo di Calca", mode="scene"
    )
    ids2 = {p[0] for p in pages2}
    assert "calca" in ids2


def test_label_helper() -> None:
    state = GameState(session_id="s", player=PlayerState(location="x"))
    assert "NARRATOR_ONLY" in label(state, "pabel", "sergente")
    learn(state, "pabel", "named")
    assert label(state, "pabel", "sergente") == "pabel (sergente)"
