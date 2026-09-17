"""Chat turn helpers: spells, sleep bucket coerce, end-scene lint."""

from pathlib import Path

from app.api.routes.gameplay import end_scene
from app.api.schemas import EndSceneRequest
from app.api import deps as api_deps
from app.api import routes as routes_mod
from app.config import settings
from app.models.narrative import NarrativeReply, NarrativeSpell, NarrativeTime
from app.services.chat_turn import coerce_time_bucket, collect_spells, looks_like_sleep
from app.services.save_manager import SaveManager


def test_collect_spells_from_message_and_reply() -> None:
    reply = NarrativeReply(
        text="Lanci.",
        time=NarrativeTime(bucket="istantanea", minutes=3),
        spells=[NarrativeSpell(name="Fly", description="volare")],
    )
    known = {"luce": {"name": "Luce", "description": "breve"}}
    out = collect_spells("[Luce — magia di luce intensa] e [Fly]", reply, known)
    assert out["Luce"]["description"] == "magia di luce intensa"
    assert out["Luce"]["output"] == "effect"
    assert out["Fly"]["description"] == "volare"
    assert out["Fly"]["output"] == "effect"


def test_collect_spells_keeps_known_tags() -> None:
    reply = NarrativeReply(
        text="",
        time=NarrativeTime(bucket="istantanea", minutes=1),
        spells=[
            NarrativeSpell(
                name="Detect Power",
                description="rileva forme di vita",
                output="effect",
                manifest="visible",
            )
        ],
    )
    known = {
        "detect power": {
            "name": "Detect Power",
            "description": "rileva",
            "output": "info",
            "manifest": "subtle",
        }
    }
    out = collect_spells("[Detect Power — rileva forme di vita]", reply, known)
    assert out["Detect Power"]["output"] == "info"
    assert out["Detect Power"]["manifest"] == "subtle"


def test_collect_spells_infers_info_for_detect() -> None:
    reply = NarrativeReply(
        text="",
        time=NarrativeTime(bucket="istantanea", minutes=1),
        spells=[],
    )
    out = collect_spells(
        "[Detect Power — rileva e localizza forme di vita]",
        reply,
        {},
    )
    assert out["Detect Power"]["output"] == "info"


def test_sleep_action_coerces_to_riposo() -> None:
    assert looks_like_sleep("mi stendo sul letto e dormo")
    assert coerce_time_bucket("lunga", "vado a letto") == "riposo"
    assert coerce_time_bucket("media", "cammino verso Carne") == "media"


def test_end_scene_returns_lint_issues(tmp_path: Path, monkeypatch) -> None:
    stories = tmp_path / "stories" / "overlord"
    seed = stories / "wiki"
    (seed / "locations").mkdir(parents=True)
    (seed / "characters").mkdir(parents=True)
    (seed / "fronts").mkdir(parents=True)
    (stories / "meta.yaml").write_text(
        "id: overlord\nname: Overlord\nstart_location: e-rantel\ndefault_front:\n",
        encoding="utf-8",
    )
    (seed / "locations" / "e-rantel.md").write_text(
        "---\nid: e-rantel\nname: E-Rantel\ntype: location\n---\n\n"
        "# Descrizione\nVedi [[nonesisto]].\n",
        encoding="utf-8",
    )
    (seed / "index.md").write_text(
        "# Index\n\n## locations\n- [[e-rantel]] -> locations/e-rantel.md\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "project_root", tmp_path)
    saves = SaveManager(root=tmp_path / "saves")
    monkeypatch.setattr(api_deps, "saves", saves)
    monkeypatch.setattr(routes_mod, "saves", saves)
    state = saves.create_session("Hero", start_location="e-rantel", story_id="overlord")
    resp = end_scene(EndSceneRequest(session_id=state.session_id))
    assert any("nonesisto" in issue for issue in resp.lint_issues)
