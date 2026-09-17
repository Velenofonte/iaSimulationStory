"""Per-session service binding (wiki clone under saves/<id>/wiki)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.episodes.consequence_engine import ConsequenceEngine
from app.story.era_loader import EraLoader
from app.story.front_engine import FrontEngine
from app.story.front_loader import FrontLoader
from app.llm.llm_client import LLMClient
from app.narrative.narrative_context import NarrativeContextAssembler
from app.narrative.narrative_engine import NarrativeEngine
from app.narrative.narrative_renderer import NarrativeRenderer
from app.persistence.save_manager import SaveManager
from app.story.story_engine import StoryEngine
from app.turn.turn_pipeline import TurnPipeline
from app.narrative.turn_resolver import TurnResolver
from app.wiki.wiki_lint import WikiLint
from app.wiki.wiki_query import WikiQuery
from app.wiki.wiki_writer import WikiWriter


@dataclass
class SessionServices:
    wiki_dir: Path
    wiki: WikiWriter
    query: WikiQuery
    lint: WikiLint
    fronts: FrontEngine
    story: StoryEngine
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
    story_id: str | None = None,
) -> SessionServices:
    saves = saves or SaveManager()
    wiki_dir = saves.wiki_dir(session_id)
    if not wiki_dir.is_dir():
        raise FileNotFoundError(f"Session wiki missing: {session_id}")
    wiki = WikiWriter(wiki_dir=wiki_dir)
    query = WikiQuery(wiki_dir=wiki_dir)
    lint = WikiLint(wiki_dir=wiki_dir, query=query)
    front_loader = FrontLoader(fronts_dir=wiki_dir / "fronts")
    fronts = FrontEngine(loader=front_loader, wiki=wiki)
    shared_llm = llm or LLMClient()
    sid = story_id
    if not sid:
        try:
            state = saves.load_game_state(session_id)
            sid = state.story_id
        except Exception:
            sid = "overlord"
    story = StoryEngine(
        fronts=fronts,
        wiki=wiki,
        era_loader=EraLoader(story_id=sid),
        front_loader=front_loader,
        llm=shared_llm,
    )
    fronts.story = story
    assembler = NarrativeContextAssembler(
        wiki=query,
        wiki_writer=wiki,
        fronts=fronts,
        story=story,
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
        story=story,
        narrative=narrative,
        consequences=consequences,
        saves=saves,
        pipeline=pipeline,
        assembler=assembler,
        resolver=resolver,
        renderer=renderer,
        llm=shared_llm,
    )
