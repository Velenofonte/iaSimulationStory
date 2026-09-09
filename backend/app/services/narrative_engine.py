"""Legacy facade: build_request for tests; production uses TurnPipeline."""

from __future__ import annotations

from app.models import GameState
from app.models.narrative import NarrativeRequest
from app.services.front_engine import FrontEngine
from app.services.llm_client import LLMClient
from app.services.narrative_context import NarrativeContextAssembler
from app.services.prompt_builder import PromptBuilder
from app.services.save_manager import SaveManager
from app.services.wiki_query import WikiQuery
from app.services.wiki_writer import WikiWriter


class NarrativeEngine:
    """Thin facade over NarrativeContextAssembler (test / tooling compatibility)."""

    def __init__(
        self,
        *,
        wiki: WikiQuery | None = None,
        wiki_writer: WikiWriter | None = None,
        fronts: FrontEngine | None = None,
        saves: SaveManager | None = None,
        assembler: NarrativeContextAssembler | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.wiki = wiki or WikiQuery()
        self.wiki_writer = wiki_writer or WikiWriter()
        self.prompts = PromptBuilder()
        self.saves = saves or SaveManager()
        self.fronts = fronts or FrontEngine(wiki=self.wiki_writer)
        self.assembler = assembler or NarrativeContextAssembler(
            wiki=self.wiki,
            wiki_writer=self.wiki_writer,
            fronts=self.fronts,
            saves=self.saves,
            prompts=self.prompts,
        )

    def build_request(self, *, state: GameState, user_message: str) -> NarrativeRequest:
        return self.assembler.build_request(state=state, user_message=user_message)
