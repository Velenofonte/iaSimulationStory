"""Tests for open threads / memories on consolidation."""

from pathlib import Path

import frontmatter

from app.models.reviews import CharacterConsolidationUpdate, ConsolidationReviewResult
from app.services.wiki_writer import WikiWriter


def test_open_threads_remove_and_dedupe_add(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    path = wiki._character_path("hero")
    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(
                    open_threads_add=[
                        "Possibile viaggio verso il villaggio carne.",
                        "Tensione con la guardia e il Consiglio di E-Rantel.",
                        "Ricerca di Mira.",
                    ]
                )
            }
        )
    )

    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(
                    open_threads_remove=["Possibile viaggio verso il villaggio carne."],
                    open_threads_add=[
                        "Tensione con la guardia e il Consiglio di E-Rantel.",
                        "Indagare la luce rossa a Carne.",
                    ],
                    location="carne",
                )
            }
        )
    )
    post = frontmatter.load(path)
    threads = wiki.get_section(post.content, "Open threads")
    assert "Possibile viaggio verso il villaggio carne." not in threads
    assert "Indagare la luce rossa a Carne." in threads
    assert "Ricerca di Mira." in threads
    assert sum(1 for t in threads if "tensione con la guardia" in t.lower()) == 1
    assert post.metadata.get("location") == "carne"


def test_open_threads_remove_substring(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(
                    open_threads_add=[
                        "Tensione con la guardia e il Consiglio di E-Rantel dopo l'incidente al Tribunale.",
                        "Tensione con la guardia e il Consiglio di E-Rantel dopo l'incidente con la sfera.",
                    ]
                )
            }
        )
    )
    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(
                    open_threads_remove=[
                        "Tensione con la guardia e il Consiglio di E-Rantel dopo l'incidente"
                    ],
                )
            }
        )
    )
    post = frontmatter.load(wiki._character_path("hero"))
    threads = wiki.get_section(post.content, "Open threads")
    assert threads == []


def test_memories_remove(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    path = wiki._character_path("hero")
    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(
                    memories_add=[
                        "Lancio di detect power.",
                        "Ha conosciuto Ludo.",
                    ]
                )
            }
        )
    )
    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(
                    memories_remove=["Lancio di detect power."],
                    memories_add=[
                        "Ha conosciuto Ludo (erborista): figlia Mira presa dal Tribunale."
                    ],
                )
            }
        )
    )
    post = frontmatter.load(path)
    memories = wiki.get_section(post.content, "Memorie")
    assert "Lancio di detect power." not in memories
    assert any("Mira" in m for m in memories)


def test_memories_absorb_prefix_duplicate(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    path = wiki._character_path("hero")
    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(
                    memories_add=[
                        "Iscritto alla gilda come Rame; scelto sterminio lupi.",
                    ]
                )
            }
        )
    )
    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(
                    memories_add=[
                        "Iscritto alla gilda come Rame; scelto sterminio lupi. Ha chiesto info sulle locande.",
                    ]
                )
            }
        )
    )
    post = frontmatter.load(path)
    memories = wiki.get_section(post.content, "Memorie")
    assert len(memories) == 1
    assert "locande" in memories[0].lower()
    assert "sterminio lupi" in memories[0].lower()


def test_memories_skip_when_existing_already_covers(tmp_path: Path) -> None:
    wiki = WikiWriter(wiki_dir=tmp_path / "wiki")
    wiki.ensure_player("Hero", "e-rantel")
    path = wiki._character_path("hero")
    dense = "Iscritto alla gilda come Rame; scelto sterminio lupi. Ha chiesto info sulle locande."
    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(memories_add=[dense])
            }
        )
    )
    wiki.apply_consolidation(
        ConsolidationReviewResult(
            character_updates={
                "hero": CharacterConsolidationUpdate(
                    memories_add=["Iscritto alla gilda come Rame; scelto sterminio lupi."]
                )
            }
        )
    )
    post = frontmatter.load(path)
    memories = wiki.get_section(post.content, "Memorie")
    assert memories == [dense]
