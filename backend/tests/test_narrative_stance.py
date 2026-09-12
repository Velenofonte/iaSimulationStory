"""Tests for passive stance detection and narrative de-duplication."""

from __future__ import annotations

import json
from pathlib import Path

from app.models.chat import ChatMessage
from app.models.narrative import NarrativeChatTurn
from app.services.narrative_stance import (
    compress_repeated_narrative,
    detect_stance,
    trim_chat_for_passive_render,
)
from tests.conftest import make_seed_story


def test_detect_stance_passive_watch() -> None:
    assert detect_stance("continuo a guardare la scena") == "passive"
    assert detect_stance("osservo la battaglia") == "passive"
    assert detect_stance("rimango fermo e guardo") == "passive"


def test_detect_stance_wait_until_change() -> None:
    assert detect_stance("aspetto che il combattimento si sbilanci") == "wait"
    assert detect_stance("attendo l'arrivo di Gazef") == "wait"
    assert detect_stance("continuo a cercare finché trovo una traccia") == "wait"


def test_detect_stance_action_with_dialogue() -> None:
    assert detect_stance('"se continua cosi ce la potrebbe fare da solo" dico a bassa voce') == "action"
    assert detect_stance("mi avvicino a Gazef") == "action"
    # "guardo X" + domanda non deve diventare passive
    assert detect_stance('guardo gazef "cosa ne vuoi fare del prigioniero?"') == "action"
    assert (
        detect_stance(
            '"bene quindi siamo tutti felici e gazef ti chiederei di non rivelare la mia forza"'
        )
        == "action"
    )


def test_detect_stance_wait_for_npc_reply() -> None:
    assert detect_stance("aspetto la risposta di gazef") == "wait"


def test_compress_repeated_narrative_strips_duplicate_dialogue() -> None:
    prior = (
        "Gazef si volta verso la cupola. "
        "«Lo consegnerò alla capitale per un interrogatorio formale. "
        "La Teocrazia deve rispondere di questo attacco.»"
    )
    new = (
        "Gazef annuisce con decisione. "
        "«Lo consegnerò alla capitale per un interrogatorio formale. "
        "La Teocrazia deve rispondere di questo attacco.» "
        "Poi abbassa la voce: «Non dirò nulla ai contadini sulla tua forza.»"
    )
    out = compress_repeated_narrative(new, prior)
    assert "capitale" not in out.lower()
    assert "contadini" in out.lower()


def test_trim_chat_keeps_latest_assistant() -> None:
    chat = [
        NarrativeChatTurn(role="user", content="osservo"),
        NarrativeChatTurn(role="assistant", content="Gazef combatte ai margini del bosco."),
        NarrativeChatTurn(role="user", content="continuo a guardare"),
        NarrativeChatTurn(role="assistant", content="L'angelo pulsa nel cielo sopra Carne."),
    ]
    trimmed = trim_chat_for_passive_render(chat)
    # Penultimo assistant rimosso; ultimo beat resta (continuita').
    assert trimmed[-1].role == "assistant"
    assert "angelo" in trimmed[-1].content.lower()
    assert not any(t.content.startswith("Gazef combatte") for t in trimmed)


def test_compress_repeated_narrative_strips_duplicate_sentences() -> None:
    prior = (
        "Gazef Stronoff combatte con scherma pura ai margini del bosco. "
        "L'angelo di pura energia domina il cielo sopra Carne."
    )
    new = (
        "Gazef Stronoff combatte con scherma pura ai margini del bosco. "
        "Uno dei suoi uomini vacilla ma la linea regge ancora."
    )
    out = compress_repeated_narrative(new, prior)
    assert "Gazef Stronoff combatte" not in out
    assert "vacilla" in out


def test_pipeline_passive_trims_chat_in_render_request(
    tmp_path: Path, monkeypatch, fake_llm
) -> None:
    from app.config import settings
    from app.services.save_manager import SaveManager
    from app.services.session_context import build_session_services

    monkeypatch.setattr(settings, "project_root", tmp_path)
    make_seed_story(tmp_path)
    saves = SaveManager(root=tmp_path / "saves")
    state = saves.create_session("Hero", start_location="carne", story_id="overlord")
    svc = build_session_services(state.session_id, saves=saves)

    saves.append_chat(state.session_id, ChatMessage(role="user", content="osservo"))
    saves.append_chat(
        state.session_id,
        ChatMessage(role="assistant", content="Gazef tiene la linea mentre l'angelo domina il cielo."),
    )

    stub = fake_llm
    stub["responses"] = [
        json.dumps(
            {
                "time": {"bucket": "istantanea", "minutes": 2},
                "location": None,
                "present": None,
                "spells": [],
                "scene_brief": ["Il PG osserva ancora."],
            }
        ),
        json.dumps({"text": "Uno scudo cede ma la linea regge."}),
    ]

    monkeypatch.setattr(svc.consequences, "should_run_present_review", lambda s: False)
    monkeypatch.setattr(svc.consequences, "should_run_consolidation_review", lambda s: False)

    svc.pipeline.run(state, "continuo a guardare la scena", svc=svc)

    render_user = stub["calls"][-1]["user"]
    payload = json.loads(render_user)
    assert payload["stance"] == "passive"
    roles = [t["role"] for t in payload["chat_recent"]]
    # Ultimo assistant tenuto per continuita' (impatto / aftermath).
    assert "assistant" in roles
    assert any(
        "angelo" in (t.get("content") or "").lower()
        for t in payload["chat_recent"]
        if t.get("role") == "assistant"
    )


def test_pipeline_wait_uses_narrative_duration_without_jumping_to_front_beat(
    tmp_path: Path, monkeypatch, fake_llm
) -> None:
    from app.config import settings
    from app.models.turn import FrontOutcome
    from app.services.save_manager import SaveManager
    from app.services.session_context import build_session_services

    monkeypatch.setattr(settings, "project_root", tmp_path)
    make_seed_story(tmp_path)
    saves = SaveManager(root=tmp_path / "saves")
    state = saves.create_session("Hero", start_location="carne", story_id="overlord")
    svc = build_session_services(state.session_id, saves=saves)
    start_minutes = state.minutes

    monkeypatch.setattr(svc.fronts, "minutes_to_next_hydratable_beat", lambda s: 120)
    elapsed: list[int] = []

    def _resolve_tick(_state, delta):
        elapsed.append(delta)
        return FrontOutcome()

    monkeypatch.setattr(svc.fronts, "resolve_tick", _resolve_tick)
    monkeypatch.setattr(svc.consequences, "should_run_present_review", lambda s: False)
    monkeypatch.setattr(svc.consequences, "should_run_consolidation_review", lambda s: False)

    fake_llm["responses"] = [
        json.dumps(
            {
                "time": {"bucket": "istantanea", "minutes": 2},
                "location": None,
                "present": None,
                "spells": [],
                "scene_brief": ["La formazione di Gazef comincia a cedere sul fianco."],
                "situations_add": ["Il fianco della formazione di Gazef sta cedendo."],
                "situations_remove": [],
            }
        ),
        json.dumps({"text": "La formazione di Gazef cede; Ainz solleva lentamente una mano."}),
    ]

    result = svc.pipeline.run(state, "aspetto che il combattimento si sbilanci", svc=svc)

    assert result.state.minutes == start_minutes + 2
    assert elapsed == [2]
    assert any(
        s.summary == "Il fianco della formazione di Gazef sta cedendo."
        for s in result.state.situations
    )
    render_payload = json.loads(fake_llm["calls"][-1]["user"])
    assert render_payload["stance"] == "wait"
    assert render_payload["fired_beat_summaries"] == []
    assert "cede" in result.reply
