"""NPC epistemic firewall: narrator-only labels on player card and situations."""

from __future__ import annotations

import json
import os

import pytest

from app.models import CharacterCard, GameState, PlayerState
from app.models.narrative import (
    NarrativeCanonFacts,
    NarrativeRequest,
    SITUATIONS_EPISTEMIC_NOTE,
)
from app.models.turn import NarrativeRenderRequest
from app.services.llm_client import LLMClient
from app.services.narrative_renderer import NarrativeRenderer
from app.services.prompt_builder import PromptBuilder
from app.services.turn_resolver import TurnResolver


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
        situations=["Missione Xylophage: partenza all'alba."],
    )
    dumped = facts.model_dump()
    assert isinstance(dumped["situations"], dict)
    assert dumped["situations"]["note"] == SITUATIONS_EPISTEMIC_NOTE
    assert dumped["situations"]["items"] == ["Missione Xylophage: partenza all'alba."]
    # Python attribute stays a plain list
    assert facts.situations == ["Missione Xylophage: partenza all'alba."]

    payload = json.loads(facts.model_dump_json())
    assert "condizioni 1-3" in payload["situations"]["note"]
    assert "Xylophage" in payload["situations"]["items"][0]


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
    assert "Xylophage" in data["canon_facts"]["situations"]["items"][0]


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
