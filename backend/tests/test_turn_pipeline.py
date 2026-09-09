"""TurnPipeline two-pass order and state updates."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.save_manager import SaveManager
from app.services.session_context import build_session_services
from tests.conftest import make_seed_story


def _session(tmp_path: Path, monkeypatch, fake_llm):
    from app.config import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    make_seed_story(tmp_path)
    saves = SaveManager(root=tmp_path / "saves")
    state = saves.create_session("Hero", start_location="e-rantel", story_id="overlord")
    svc = build_session_services(state.session_id, saves=saves)
    return state, svc, fake_llm


def test_pipeline_resolve_then_render_order(tmp_path: Path, monkeypatch, fake_llm) -> None:
    state, svc, stub = _session(tmp_path, monkeypatch, fake_llm)
    stub["responses"] = [
        json.dumps(
            {
                "time": {"bucket": "istantanea", "minutes": 3},
                "location": "carne",
                "present": ["enri"],
                "spells": [],
                "scene_brief": ["Arrivi a Carne."],
            }
        ),
        json.dumps({"text": "Arrivi nel villaggio di Carne. Enri ti guarda."}),
    ]
    result = svc.pipeline.run(state, "vado a Carne", svc=svc)
    assert len(stub["calls"]) == 2
    # First call = resolve (no scene_brief in user? request has no scene_brief field)
    u0 = stub["calls"][0]["user"]
    u1 = stub["calls"][1]["user"]
    assert '"player_action"' in u0
    assert '"active_arc"' in u0 or '"canon_facts"' in u0
    assert '"scene_brief"' in u1
    assert "Arrivi nel villaggio" in result.reply
    assert result.state.player.location == "carne"
    assert "enri" in result.state.characters_active


def test_pipeline_beat_in_render_without_meta_suffix(tmp_path: Path, monkeypatch, fake_llm) -> None:
    state, svc, stub = _session(tmp_path, monkeypatch, fake_llm)
    stub["responses"] = [
        json.dumps(
            {
                "time": {"bucket": "lunga", "minutes": 600},
                "location": None,
                "present": None,
                "spells": [],
                "scene_brief": ["Cammini a lungo."],
            }
        ),
        json.dumps({"text": "Cammini per ore. Un rumore spezza la notte."}),
    ]

    def _forced(state, bucket, minutes, **_kwargs):
        from app.models.turn import FrontOutcome

        return (
            "",
            FrontOutcome(
                fired_beats=["beat_x"],
                beat_summaries=["Rumore nella notte"],
                interrupt_hint="Rumore nella notte",
            ),
        )

    monkeypatch.setattr(svc.pipeline, "_advance_clock", _forced)
    result = svc.pipeline.run(state, "viaggio lungo", svc=svc)
    assert "Cammini per ore." in result.reply
    assert "tragitto si interrompe" not in result.reply
    assert "svegli" not in result.reply.lower()
    u1 = stub["calls"][1]["user"]
    assert "Rumore nella notte" in u1
    assert "fired_beat_summaries" in u1


def test_pipeline_single_save(tmp_path: Path, monkeypatch, fake_llm) -> None:
    state, svc, stub = _session(tmp_path, monkeypatch, fake_llm)
    stub["responses"] = [
        json.dumps(
            {
                "time": {"bucket": "istantanea", "minutes": 2},
                "location": None,
                "present": [],
                "spells": [],
                "scene_brief": ["Guardi intorno."],
            }
        ),
        json.dumps({"text": "La piazza e' quieta."}),
    ]
    saves_calls: list[str] = []
    real_save = svc.saves.save_game_state

    def _track(s):
        saves_calls.append(s.session_id)
        return real_save(s)

    monkeypatch.setattr(svc.saves, "save_game_state", _track)
    # Disable reviews
    monkeypatch.setattr(svc.consequences, "should_run_present_review", lambda s: False)
    monkeypatch.setattr(svc.consequences, "should_run_consolidation_review", lambda s: False)
    svc.pipeline.run(state, "guardo", svc=svc)
    assert len(saves_calls) == 1
