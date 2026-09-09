"""Per-session service binding (wiki clone under saves/<id>/wiki)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.consequence_engine import ConsequenceEngine
from app.services.front_engine import FrontEngine
from app.services.front_loader import FrontLoader
from app.services.llm_client import LLMClient
from app.services.narrative_context import NarrativeContextAssembler
from app.services.narrative_engine import NarrativeEngine
from app.services.narrative_renderer import NarrativeRenderer
from app.services.save_manager import SaveManager
from app.services.turn_pipeline import TurnPipeline
from app.services.turn_resolver import TurnResolver
from app.services.wiki_lint import WikiLint
from app.services.wiki_query import WikiQuery
from app.services.wiki_writer import WikiWriter


@dataclass
class SessionServices:
    wiki_dir: Path
    wiki: WikiWriter
    query: WikiQuery
    lint: WikiLint
    fronts: FrontEngine
    narrative: NarrativeEngine
    consequences: ConsequenceEngine
    saves: SaveManager
    pipeline: TurnPipeline
    assembler: NarrativeContextAssembler
    resolver: TurnResolver
    renderer: NarrativeRenderer
    llm: LLMClient


def build_session_services(
    session_id: str,
    *,
    saves: SaveManager | None = None,
    llm: LLMClient | None = None,
) -> SessionServices:
    saves = saves or SaveManager()
    wiki_dir = saves.wiki_dir(session_id)
    if not wiki_dir.is_dir():
        raise FileNotFoundError(f"Session wiki missing: {session_id}")
    wiki = WikiWriter(wiki_dir=wiki_dir)
    query = WikiQuery(wiki_dir=wiki_dir)
    lint = WikiLint(wiki_dir=wiki_dir, query=query)
    fronts = FrontEngine(
        loader=FrontLoader(fronts_dir=wiki_dir / "fronts"),
        wiki=wiki,
    )
    shared_llm = llm or LLMClient()
    assembler = NarrativeContextAssembler(
        wiki=query,
        wiki_writer=wiki,
        fronts=fronts,
        saves=saves,
    )
    resolver = TurnResolver(llm=shared_llm)
    renderer = NarrativeRenderer(llm=shared_llm)
    narrative = NarrativeEngine(
        wiki=query,
        wiki_writer=wiki,
        fronts=fronts,
        saves=saves,
        assembler=assembler,
        llm=shared_llm,
    )
    consequences = ConsequenceEngine(
        wiki_writer=wiki,
        lint=lint,
        fronts=fronts,
        saves=saves,
        llm=shared_llm,
    )
    pipeline = TurnPipeline(
        assembler=assembler,
        resolver=resolver,
        renderer=renderer,
        fronts=fronts,
        wiki=wiki,
        query=query,
        saves=saves,
        consequences=consequences,
    )
    return SessionServices(
        wiki_dir=wiki_dir,
        wiki=wiki,
        query=query,
        lint=lint,
        fronts=fronts,
        narrative=narrative,
        consequences=consequences,
        saves=saves,
        pipeline=pipeline,
        assembler=assembler,
        resolver=resolver,
        renderer=renderer,
        llm=shared_llm,
    )
