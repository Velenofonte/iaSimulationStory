from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_root: Path = Path(__file__).resolve().parents[2]
    openai_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    # Se impostato, usa un endpoint OpenAI-compatible (es. Azure / DeepSeek diretto).
    llm_api_base_url: str = ""
    # Endpoint OpenAI-compatible Gemini (Google AI).
    gemini_api_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    openrouter_api_base_url: str = "https://openrouter.ai/api/v1"
    llm_model_narrative: str = "gpt-4o-mini"
    llm_model_resolve: str = ""
    llm_model_render: str = ""
    llm_model_review: str = "gpt-4o-mini"
    llm_model_ingest: str = "gpt-4o-mini"
    present_review_every_n: int = 5
    consolidate_every_n: int = 12
    undo_checkpoint_depth: int = 3
    recent_chat_messages: int = 20
    wiki_page_cap: int = 6
    default_story_id: str = "overlord"

    # Token budget knobs. 0 = no limit / feature off. Defaults match current behaviour.
    # Suggested tighter values later: budget 4500, chat 8, old_cap 240, excerpt 320,
    # tier 100/250/450, review 12/18, output 900.
    narrative_token_budget: int = 0
    narrative_chat_messages: int = 20
    narrative_chat_old_char_cap: int = 0
    world_excerpt_chars: int = 900
    card_section_chars: int = 300
    card_budget_minimal: int = 0
    card_budget_growing: int = 0
    card_budget_canonical: int = 0
    review_chat_messages: int = 20
    consolidate_chat_messages: int = 24
    llm_max_output_tokens: int = 0
    # Limite parole sulla prosa Pass 2 (render). 0 = nessun tetto.
    narrative_max_words: int = 0
    narrative_dedup_world_cards: bool = False
    narrative_spellbook_on_demand: bool = False
    review_state_slice: bool = False

    @property
    def stories_dir(self) -> Path:
        return self.project_root / "stories"

    def story_dir(self, story_id: str) -> Path:
        return self.stories_dir / story_id

    def story_wiki_seed(self, story_id: str) -> Path:
        return self.story_dir(story_id) / "wiki"

    def story_meta_path(self, story_id: str) -> Path:
        return self.story_dir(story_id) / "meta.yaml"

    @property
    def wiki_dir(self) -> Path:
        """Seed wiki della storia default (ingest / tool CLI)."""
        return self.story_wiki_seed(self.default_story_id)

    @property
    def fronts_dir(self) -> Path:
        return self.wiki_dir / "fronts"

    @property
    def raw_dir(self) -> Path:
        return self.project_root / "raw"

    @property
    def templates_dir(self) -> Path:
        return self.project_root / "templates"

    @property
    def saves_dir(self) -> Path:
        return self.project_root / "saves"

    @property
    def prompts_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "prompts"


settings = Settings()
