"""Fired beat summary reflection + one render retry."""

from __future__ import annotations

import json

from app.models.narrative import NarrativeCanonFacts
from app.models.turn import NarrativeRenderRequest
from app.narrative.narrative_renderer import (
    NarrativeRenderer,
    fired_summaries_reflected,
    live_outcome_displaced,
    summary_key_tokens,
)


def test_summary_key_tokens_and_reflection() -> None:
    tokens = summary_key_tokens("Un meteorite apre la breccia. La difesa collassa.")
    assert "meteorite" in [t.casefold() for t in tokens]
    assert "breccia" in [t.casefold() for t in tokens]
    summaries = ["Un meteorite apre la breccia. La difesa collassa."]
    assert fired_summaries_reflected(
        "Il meteorite squarcia il muro; la breccia si apre sotto i tuoi piedi.",
        summaries,
    )
    assert not fired_summaries_reflected(
        "Osservi il camminamento: tutto e' quieto piu' a nord.",
        summaries,
    )


def test_summary_tokens_skip_names_already_in_scene() -> None:
    """Repeating the actor's name is not proof the event happened."""
    summary = "Il capo si nomina signore; il colpo apre la breccia. La difesa collassa."
    scene = {"capo", "signore"}
    tokens = [t.casefold() for t in summary_key_tokens(summary, limit=3, exclude=scene)]
    assert "capo" not in tokens
    assert "breccia" in tokens or "colpo" in tokens
    # Prose that only names the actor again must not count as reflected
    assert not fired_summaries_reflected(
        "Il capo ti guarda: quando cadra', verra' a prenderti.",
        [summary],
        exclude=scene,
    )
    assert fired_summaries_reflected(
        "Il colpo apre la breccia sotto i tuoi piedi; la difesa collassa.",
        [summary],
        exclude=scene,
    )


def test_live_outcome_displaced_detects_elsewhere() -> None:
    live = {"id": "beat_x", "place": "wall", "status": "live"}
    assert live_outcome_displaced(
        "Il soldato dice che e' gia' successo a nord, in un altro settore.",
        front_live=live,
    )
    assert live_outcome_displaced(
        "Hanno chiuso il fatto piu' lontano, dall'altra parte del tratto.",
        front_live=live,
    )
    assert not live_outcome_displaced(
        "La figura mascherata ti ascolta; il colpo non e' ancora partito.",
        front_live=live,
    )
    assert not live_outcome_displaced("Qualcosa succede.", front_live=None)


def test_renderer_retries_when_summaries_omitted(fake_llm) -> None:
    stub = fake_llm
    stub["responses"] = [
        json.dumps({"text": "Guardi il camminamento. Nulla di nuovo."}),
        json.dumps(
            {
                "text": (
                    "Un meteorite apre la breccia sotto i tuoi piedi; "
                    "la difesa collassa nel caos."
                )
            }
        ),
    ]
    req = NarrativeRenderRequest(
        canon_facts=NarrativeCanonFacts(
            location="great-wall-south-trail",
            time="Giorno 1 — sera",
        ),
        player_action="scruto il muro",
        stance="passive",
        scene_brief=["Osservi il camminamento."],
        fired_beat_summaries=[
            "Un meteorite apre la breccia. La difesa collassa.",
        ],
    )
    text = NarrativeRenderer().render(req)
    assert "meteorite" in text.lower() or "breccia" in text.lower()
    assert len(stub["calls"]) == 2
    assert "Retry vincolante" in stub["calls"][1]["system"]


def test_renderer_retries_when_live_displaced(fake_llm) -> None:
    stub = fake_llm
    stub["responses"] = [
        json.dumps(
            {
                "text": (
                    "Il soldato sussurra che e' gia' accaduto a nord, "
                    "in un altro settore del tratto."
                )
            }
        ),
        json.dumps(
            {
                "text": (
                    "Davanti a te la pressione e' ancora aperta: il demone ascolta, "
                    "il colpo non e' partito."
                )
            }
        ),
    ]
    req = NarrativeRenderRequest(
        canon_facts=NarrativeCanonFacts(
            location="wall-south",
            time="Giorno 1 — sera",
            extra={
                "front_live": {
                    "id": "breach",
                    "title": "Breach",
                    "place": "wall",
                    "bullets": ["A single strike opens the wall."],
                    "status": "live",
                }
            },
        ),
        player_action="parlo col capo",
        stance="action",
        scene_brief=["Dialogo col capo; beat ancora aperto."],
        fired_beat_summaries=[],
    )
    text = NarrativeRenderer().render(req)
    assert "nord" not in text.lower() or "non e' partito" in text.lower()
    assert len(stub["calls"]) == 2
    assert "spostato" in stub["calls"][1]["system"].lower() or "front_live" in stub["calls"][1]["system"]
