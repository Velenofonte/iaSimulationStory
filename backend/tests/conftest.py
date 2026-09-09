from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.config import settings


def make_seed_story(tmp_path: Path, *, story_id: str = "overlord") -> Path:
    """Create a minimal story seed (meta + wiki) under tmp_path/stories/<story_id>."""
    stories = tmp_path / "stories" / story_id
    seed = stories / "wiki"
    (seed / "locations").mkdir(parents=True)
    (seed / "characters").mkdir(parents=True)
    (seed / "fronts").mkdir(parents=True)
    (seed / "spellbooks").mkdir(parents=True)
    (stories / "meta.yaml").write_text(
        f"id: {story_id}\n"
        f"name: Overlord\n"
        f"start_location: e-rantel\n"
        f"default_front:\n"
        f"playable_characters:\n"
        f"  - enri\n"
        f"races:\n"
        f"  - id: human\n"
        f"    name: Umano\n"
        f"  - id: elf\n"
        f"    name: Elfo\n",
        encoding="utf-8",
    )
    (seed / "locations" / "e-rantel.md").write_text(
        "---\nid: e-rantel\nname: E-Rantel\ntype: location\ntier: canonical\n---\n\n"
        "# Descrizione\nCitta'.\n\n# Eventi\n\n# Tensioni\n",
        encoding="utf-8",
    )
    (seed / "characters" / "enri.md").write_text(
        "---\nid: enri\nname: Enri Emmot\ntype: character\ntier: canonical\n---\n\n"
        "# Personalita\nCoraggiosa.\n\n# Knowledge scope\nsa: Carne, agricoltura\n"
        "non sa: Nazarick\n",
        encoding="utf-8",
    )
    (seed / "fronts" / "carne_arc.yaml").write_text(
        "id: carne_arc\n"
        "name: Arco di Carne\n"
        "start:\n"
        "  day: 1\n"
        "  minutes: 480\n"
        "  beat: start_beat\n"
        "flags_initial:\n"
        "  carne_intact: true\n"
        "beats:\n"
        "  - id: start_beat\n"
        "    title: Inizio\n"
        "    place: e-rantel\n"
        "    hours_after_previous: 0\n"
        "    scene_canon: |\n"
        "      Inizio test.\n"
        "    on_fire:\n"
        "      wiki_writes:\n"
        "        - entity: e-rantel\n"
        "          events_add:\n"
        "            - \"Voci iniziali dall'arco di Carne (test).\"\n"
        "  - id: later_beat\n"
        "    title: Dopo\n"
        "    place: e-rantel\n"
        "    hours_after_previous: 24\n"
        "    scene_canon: |\n"
        "      Continua.\n"
        "    on_fire:\n"
        "      wiki_writes:\n"
        "        - entity: e-rantel\n"
        "          events_add:\n"
        "            - \"Arco di Carne chiuso (test post-arco).\"\n"
        "          tensions_add:\n"
        "            - \"Rumor dalla frontiera (test).\"\n"
        "    resolves_arc: weak\n",
        encoding="utf-8",
    )
    (seed / "index.md").write_text(
        "# Index\n\n"
        "## locations\n- [[e-rantel]] -> locations/e-rantel.md\n\n"
        "## characters\n- [[enri]] -> characters/enri.md\n",
        encoding="utf-8",
    )
    return stories


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point settings.project_root at a temporary directory."""
    monkeypatch.setattr(settings, "project_root", tmp_path)
    return tmp_path


@pytest.fixture
def seed_story(project_root: Path) -> Path:
    """project_root fixture + minimal overlord seed wiki."""
    return make_seed_story(project_root)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch):
    """Replace LLMClient.complete with a controllable stub.

    Tests can set `fake_llm.responses` to a list of JSON strings consumed FIFO.
    """
    from app.services import llm_client as llm_mod

    state: dict[str, Any] = {"responses": [], "calls": []}

    def _complete(self, *, system: str, user: str, model=None, temperature: float = 0.8) -> str:
        self.last_usage = None
        state["calls"].append({"system": system, "user": user, "model": model})
        if state["responses"]:
            return state["responses"].pop(0)
        return llm_mod.LLMClient._mock_response(self, user)

    monkeypatch.setattr(llm_mod.LLMClient, "complete", _complete)
    return state
