"""Per-adventure wiki isolation: seed clone + no cross-session bleed."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from app.config import settings
from app.models.reviews import CharacterConsolidationUpdate, ConsolidationReviewResult, WikiPlaceUpdate
from app.services.save_manager import SaveManager
from app.services.session_context import build_session_services


def test_session_wiki_isolation(tmp_path: Path, monkeypatch) -> None:
    stories = tmp_path / "stories" / "overlord"
    seed = stories / "wiki"
    (seed / "locations").mkdir(parents=True)
    (seed / "characters").mkdir(parents=True)
    (seed / "fronts").mkdir(parents=True)
    (seed / "spellbooks").mkdir(parents=True)
    (stories / "meta.yaml").write_text(
        "id: overlord\nname: Overlord\nstart_location: e-rantel\ndefault_front:\n",
        encoding="utf-8",
    )
    (seed / "locations" / "e-rantel.md").write_text(
        "---\nid: e-rantel\nname: E-Rantel\ntype: location\n---\n\n"
        "# Descrizione\nCitta'.\n\n# Eventi\n\n# Tensioni\n",
        encoding="utf-8",
    )
    (seed / "index.md").write_text(
        "# Index\n\n## locations\n- [[e-rantel]] -> locations/e-rantel.md\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "project_root", tmp_path)

    saves = SaveManager(root=tmp_path / "saves")
    # story_catalog uses settings.stories_dir property → project_root / stories
    a = saves.create_session("Alice", story_id="overlord")
    b = saves.create_session("Bob", story_id="overlord")

    assert a.story_id == "overlord"
    assert (tmp_path / "saves" / a.session_id / "wiki" / "locations" / "e-rantel.md").exists()

    svc_a = build_session_services(a.session_id, saves=saves)
    svc_a.wiki.ensure_player("Alice", "e-rantel")
    svc_a.wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "alice": CharacterConsolidationUpdate(
                    memories_add=["Ha bruciato il Tribunale di E-Rantel."]
                )
            },
            location_updates={
                "e-rantel": WikiPlaceUpdate(
                    events_add=["Tribunale Arcano distrutto dal giocatore."]
                )
            },
        )
    )
    svc_a.wiki.track_spells("Alice", {"Fireball": "palla di fuoco"})

    svc_b = build_session_services(b.session_id, saves=saves)
    post_b = frontmatter.load(svc_b.wiki_dir / "locations" / "e-rantel.md")
    assert "Tribunale Arcano distrutto" not in post_b.content
    assert svc_b.wiki.read_spellbook("Bob") == []

    post_seed = frontmatter.load(seed / "locations" / "e-rantel.md")
    assert "Tribunale Arcano distrutto" not in post_seed.content
    assert not (seed / "spellbooks" / "alice.md").exists()

    post_a = frontmatter.load(svc_a.wiki_dir / "locations" / "e-rantel.md")
    assert "Tribunale Arcano distrutto" in post_a.content
    assert any(s["name"] == "Fireball" for s in svc_a.wiki.read_spellbook("Alice"))
