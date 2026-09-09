from __future__ import annotations

from app.config import settings
from app.models.narrative import NarrativeRequest, NarrativeTime
from app.models.turn import TurnResolution
from app.services.llm_client import LLMClient
from app.services.token_estimate import estimate_tokens


class TurnResolver:
    def __init__(self, *, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self.last_tokens: tuple[int, int, int] = (0, 0, 0)

    def resolve(self, request: NarrativeRequest) -> TurnResolution:
        system = self.llm.load_prompt("turn_resolve")
        user_prompt = request.model_dump_json()
        tokens_system = estimate_tokens(system)
        tokens_user = estimate_tokens(user_prompt)
        model = settings.llm_model_resolve or settings.llm_model_narrative
        try:
            result = self.llm.complete_json(
                system=system,
                user=user_prompt,
                schema=TurnResolution,
                model=model,
                temperature=0.3,
            )
        except Exception:
            result = self._fallback()
        usage = self.llm.last_usage
        if usage and usage.get("prompt_tokens"):
            prompt = int(usage["prompt_tokens"])
            total_est = tokens_system + tokens_user
            if total_est > 0:
                tokens_system = max(1, int(round(prompt * tokens_system / total_est)))
                tokens_user = max(0, prompt - tokens_system)
            else:
                tokens_system, tokens_user = prompt, 0
            self.last_tokens = (prompt, tokens_system, tokens_user)
        else:
            self.last_tokens = (
                tokens_system + tokens_user,
                tokens_system,
                tokens_user,
            )
        return result

    @staticmethod
    def _fallback() -> TurnResolution:
        return TurnResolution(
            time=NarrativeTime(bucket="istantanea", minutes=3),
            location=None,
            present=None,
            spells=[],
            scene_brief=[],
        )
