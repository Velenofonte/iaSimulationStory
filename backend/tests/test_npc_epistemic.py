"""NPC epistemic firewall: narrator-only labels on player card and situations."""

from __future__ import annotations

import json

import pytest

from app.models import CharacterCard, GameState, PlayerState
from app.models.game_state import CharacterRuntime, NpcKnowledgeFact
from app.models.narrative import (
    NarrativeCanonFacts,
    NarrativeRequest,
    NarrativeTime,
    SITUATIONS_EPISTEMIC_NOTE,
)
from app.models.reviews import (
    CharacterConsolidationUpdate,
    ConsolidationReviewResult,
    PresentReviewResult,
)
from app.models.turn import NarrativeRenderRequest, SceneStateDelta, TurnResolution
from app.services.llm_client import LLMClient
from app.services.narrative_renderer import NarrativeRenderer
from app.services.prompt_builder import PromptBuilder
from app.services.state_reducer import (
    apply_scene_delta,
    filter_npc_knowledge_add_only,
    present_review_to_delta,
    resolution_to_delta,
)
from app.services.turn_resolver import TurnResolver
from app.services.wiki_writer import WikiWriter


def test_player_card_marks_memories_and_open_threads_narrator_only() -> None:
    body = (
        "# Capacita di combattimento\nLv 100.\n\n"
        "# Memorie\nIscritto alla gilda.\n\n"
        "# Open threads\nCompletare missione segreta Xylophage entro alba.\n"
    )
    card = CharacterCard(
        id="hero",
        name="Hero",
        tier="minimal",
        role="player",
        body=body,
    )
    text = PromptBuilder().build_prompt_card(card)
    assert "Memorie (SOLO NARRATORE, non conoscenza NPC):" in text
    assert "Open threads (SOLO NARRATORE, non conoscenza NPC):" in text
    assert "Xylophage" in text
    assert "Capacita di combattimento:" in text
    assert "Capacita di combattimento (SOLO NARRATORE" not in text


def test_player_render_card_strips_memories_and_open_threads() -> None:
    body = (
        "# Aspetto fisico\nCapelli neri.\n\n"
        "# Memorie\nIscritto alla gilda.\n\n"
        "# Open threads\nMissione lupi all'alba.\n"
    )
    card = CharacterCard(
        id="hero",
        name="Hero",
        tier="minimal",
        role="player",
        body=body,
    )
    resolve_text = PromptBuilder().build_prompt_card(card, render=False)
    render_text = PromptBuilder().build_prompt_card(card, render=True)
    assert "Open threads" in resolve_text
    assert "Missione lupi" in resolve_text
    assert "Open threads" not in render_text
    assert "Memorie" not in render_text
    assert "Missione lupi" not in render_text
    assert "Aspetto fisico" in render_text


def test_npc_card_includes_sa_questa_partita_from_runtime() -> None:
    card = CharacterCard(
        id="kael",
        name="Kael",
        tier="minimal",
        role="ally",
        body="# Personalita\nAffidabile.\n",
    )
    runtime = {
        "npc_knowledge": [
            {"id": "quest_wolves_start", "summary": "Missione lupi all'alba col PG"},
        ]
    }
    text = PromptBuilder().build_prompt_card(card, runtime, render=True)
    assert "Sa (questa partita):" in text
    assert "quest_wolves_start: Missione lupi all'alba col PG" in text


def test_npc_card_does_not_mark_memories_narrator_only() -> None:
    body = "# Memorie\nHa visto il PG.\n# Open threads\nTrovare X.\n"
    card = CharacterCard(id="npc", name="Npc", tier="minimal", role="ally", body=body)
    text = PromptBuilder().build_prompt_card(card)
    assert "SOLO NARRATORE" not in text


def test_canon_facts_situations_dump_wraps_with_epistemic_note() -> None:
    facts = NarrativeCanonFacts(
        location="shop",
        time="Giorno 1 · pomeriggio · 16:00",
        present=["alchimista"],
        offscreen=["nfirea — retrobottega: erbe"],
        situations=["Missione Xylophage: partenza all'alba."],
    )
    dumped = facts.model_dump(mode="json")
    assert isinstance(dumped["situations"], dict)
    assert dumped["situations"]["note"] == SITUATIONS_EPISTEMIC_NOTE
    assert dumped["situations"]["items"][0]["summary"] == (
        "Missione Xylophage: partenza all'alba."
    )
    assert dumped["situations"]["items"][0]["id"]
    assert dumped["offscreen"] == ["nfirea — retrobottega: erbe"]
    assert len(facts.situations) == 1
    assert facts.situations[0].summary == "Missione Xylophage: partenza all'alba."

    payload = json.loads(facts.model_dump_json())
    assert "NARRATOR_ONLY" in payload["situations"]["note"]
    assert "Xylophage" in payload["situations"]["items"][0]["summary"]
    assert "nfirea" in payload["offscreen"][0]


def test_narrative_request_dump_includes_situations_wrapper() -> None:
    req = NarrativeRequest(
        canon_facts=NarrativeCanonFacts(
            location="shop",
            time="mattina",
            present=["alchimista"],
            situations=["Scadenza missione Xylophage all'alba."],
        ),
        player_action='"Le pozioni qui sono di buona qualita?"',
        character_cards=[
            "ID: hero\nRuolo: player\n"
            "Open threads (SOLO NARRATORE, non conoscenza NPC): Xylophage all'alba."
        ],
    )
    raw = req.model_dump_json()
    data = json.loads(raw)
    assert data["canon_facts"]["situations"]["note"]
    assert "Xylophage" in data["canon_facts"]["situations"]["items"][0]["summary"]


def test_npc_knowledge_upsert_by_id() -> None:
    state = GameState(session_id="s", player=PlayerState(name="Hero"))
    apply_scene_delta(
        state,
        SceneStateDelta(
            npc_knowledge_upsert={
                "kael": [
                    NpcKnowledgeFact(
                        id="quest_wolves_start",
                        summary="Missione lupi all'alba col PG",
                    )
                ]
            }
        ),
    )
    apply_scene_delta(
        state,
        SceneStateDelta(
            npc_knowledge_upsert={
                "kael": [
                    NpcKnowledgeFact(
                        id="quest_wolves_start",
                        summary="Missione lupi all'alba col PG; porta veleno",
                    ),
                    NpcKnowledgeFact(
                        id="quest_wolves_incident",
                        summary="Incidente sul tragitto",
                    ),
                ]
            }
        ),
    )
    facts = state.characters["kael"].npc_knowledge
    by_id = {f.id: f.summary for f in facts}
    assert by_id["quest_wolves_start"] == "Missione lupi all'alba col PG; porta veleno"
    assert by_id["quest_wolves_incident"] == "Incidente sul tragitto"
    assert len(facts) == 2


def test_resolution_propagates_npc_knowledge() -> None:
    res = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        npc_knowledge_upsert={
            "kael": [{"id": "quest_wolves_start", "summary": "Missione lupi"}]
        },
    )
    delta = resolution_to_delta(res)
    assert "kael" in delta.npc_knowledge_upsert
    assert delta.npc_knowledge_upsert["kael"][0].id == "quest_wolves_start"


def test_npc_knowledge_upsert_drops_npcs_not_in_cast() -> None:
    res = TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=3),
        present=["doran"],
        npc_knowledge_upsert={
            "doran": [{"id": "vena", "summary": "Vena sotto le pietre"}],
            "impiegato-gilda": [{"id": "vena", "summary": "Vena sotto le pietre"}],
        },
    )
    delta = resolution_to_delta(res, previous_present=["doran", "kaelen"])
    assert "doran" in delta.npc_knowledge_upsert
    assert "impiegato-gilda" not in delta.npc_knowledge_upsert


def test_npc_knowledge_dropped_on_move_when_present_omitted() -> None:
    res = TurnResolution(
        time=NarrativeTime(bucket="breve", minutes=30),
        location="gilda-avventurieri",
        present=None,
        npc_knowledge_upsert={
            "doran": [{"id": "x", "summary": "il party non e' in gilda"}],
        },
    )
    delta = resolution_to_delta(
        res,
        previous_location="rovine-sud",
        previous_present=["doran"],
    )
    assert delta.characters_active == []
    assert delta.npc_knowledge_upsert == {}


def test_present_review_can_update_existing_npc_knowledge() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(name="Hero"),
        characters={
            "kael": CharacterRuntime(
                npc_knowledge=[
                    NpcKnowledgeFact(
                        id="quest_wolves_start",
                        summary="Missione lupi (dal resolve)",
                    )
                ]
            )
        },
    )
    result = PresentReviewResult(
        characters_active=["kael"],
        npc_knowledge_upsert={
            "kael": [
                {
                    "id": "quest_wolves_start",
                    "summary": "Missione lupi aggiornata dalla review",
                },
                {
                    "id": "quest_wolves_told_milo",
                    "summary": "Fatto nuovo dalla chat",
                },
            ]
        },
    )
    delta = present_review_to_delta(result, state=state)
    by_delta = {f.id: f.summary for f in delta.npc_knowledge_upsert.get("kael", [])}
    assert by_delta["quest_wolves_start"] == "Missione lupi aggiornata dalla review"
    assert by_delta["quest_wolves_told_milo"] == "Fatto nuovo dalla chat"
    apply_scene_delta(state, delta)
    by_id = {f.id: f.summary for f in state.characters["kael"].npc_knowledge}
    assert by_id["quest_wolves_start"] == "Missione lupi aggiornata dalla review"
    assert by_id["quest_wolves_told_milo"] == "Fatto nuovo dalla chat"


def test_filter_npc_knowledge_add_only() -> None:
    state = GameState(
        session_id="s",
        characters={
            "milo": CharacterRuntime(
                npc_knowledge=[NpcKnowledgeFact(id="a", summary="gia' noto")]
            )
        },
    )
    filtered = filter_npc_knowledge_add_only(
        state,
        {
            "milo": [
                NpcKnowledgeFact(id="a", summary="riscrittura"),
                NpcKnowledgeFact(id="b", summary="nuovo"),
                NpcKnowledgeFact(id="a", summary="gia' noto"),  # no-op
            ]
        },
    )
    ids = {f.id: f.summary for f in filtered["milo"]}
    assert ids["a"] == "riscrittura"
    assert ids["b"] == "nuovo"


def test_render_lenses_segregate_milo_and_kael() -> None:
    milo = CharacterCard(
        id="milo",
        name="Milo",
        tier="minimal",
        body="# Knowledge scope\nsa: pozioni.\n",
    )
    kael = CharacterCard(
        id="kael",
        name="Kael",
        tier="minimal",
        body="# Knowledge scope\nsa: missioni.\n",
    )
    milo_text = PromptBuilder().build_prompt_card(
        milo,
        {"npc_knowledge": []},
        render=True,
    )
    kael_text = PromptBuilder().build_prompt_card(
        kael,
        {
            "npc_knowledge": [
                {
                    "id": "quest_wolves_start",
                    "summary": "Missione lupi all'alba col PG",
                }
            ]
        },
        render=True,
    )
    assert "Missione lupi" not in milo_text
    assert "quest_wolves_start: Missione lupi all'alba col PG" in kael_text


def test_relationship_section_merges_score_and_summary(tmp_path) -> None:
    wiki_dir = tmp_path / "wiki"
    (wiki_dir / "characters").mkdir(parents=True)
    sheet = wiki_dir / "characters" / "kael.md"
    sheet.write_text(
        "---\nid: kael\nname: Kael\ntype: character\ntier: minimal\n---\n\n"
        "# Relazione col giocatore\n\n0\n",
        encoding="utf-8",
    )
    writer = WikiWriter(wiki_dir=wiki_dir)
    writer.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "kael": CharacterConsolidationUpdate(
                    relationship=2,
                    relationship_summary_add=[
                        "Ha fatto col PG la missione lupi; incidente sul tragitto."
                    ],
                )
            }
        )
    )
    body = sheet.read_text(encoding="utf-8")
    assert "Punteggio: 2" in body
    assert "Ha fatto col PG la missione lupi" in body
    # second consolidation preserves score and appends
    writer.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "kael": CharacterConsolidationUpdate(
                    relationship_summary_add=["Si sono rivisti in locanda."]
                )
            }
        )
    )
    body2 = sheet.read_text(encoding="utf-8")
    assert "Punteggio: 2" in body2
    assert "Si sono rivisti in locanda" in body2
    assert "missione lupi" in body2


def _llm_available() -> bool:
    return LLMClient().available


@pytest.mark.skipif(not _llm_available(), reason="Nessuna API LLM configurata")
def test_behavioral_npc_does_not_leak_hidden_situation() -> None:
    """PG parla solo di pozioni; situation nascosta non deve apparire in prosa/brief."""
    hidden = "Xylophage"
    situation = f"Missione {hidden}: partenza all'alba; PG iscritto."
    action = '"Ho sentito che fate pozioni di ottima qualita."'
    cards = [
        (
            "ID: hero\nNome: Hero\nTier: minimal\nRuolo: player\n"
            f"Open threads (SOLO NARRATORE, non conoscenza NPC): Completare {hidden} all'alba.\n"
            "Equipaggiamento: bastone.\n"
        ),
        (
            "ID: alchimista\nNome: Alchimista\nTier: minimal\n"
            "Personalita: Cortese, parla solo di merci.\n"
            "Knowledge scope: sa: pozioni e prezzi. non sa: missioni del PG.\n"
        ),
    ]
    canon = NarrativeCanonFacts(
        location="negozio-di-pozioni",
        time="Giorno 1 · pomeriggio · 16:00",
        present=["alchimista"],
        situations=[situation],
    )

    resolve_req = NarrativeRequest(
        canon_facts=canon,
        character_cards=cards,
        player_action=action,
        stance="action",
        chat_recent=[],
    )
    resolution = TurnResolver().resolve(resolve_req)
    brief_blob = " ".join(resolution.scene_brief).lower()
    assert hidden.lower() not in brief_blob, (
        f"scene_brief ha leakato il fatto nascosto: {resolution.scene_brief!r}"
    )

    render_req = NarrativeRenderRequest(
        canon_facts=canon,
        player_action=action,
        stance="action",
        scene_brief=list(resolution.scene_brief) or [
            "Alchimista — qualita' pozioni — risponde sul merce"
        ],
        character_cards=cards,
        chat_recent=[],
    )
    text = NarrativeRenderer().render(render_req)
    assert hidden.lower() not in text.lower(), (
        f"prosa ha leakato il fatto nascosto: {text!r}"
    )
