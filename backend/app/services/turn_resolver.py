from __future__ import annotations

from app.config import settings
from app.models.narrative import NarrativeRequest, NarrativeTime
from app.models.turn import TurnResolution
from app.services.llm_client import LLMClient
from app.services.token_estimate import estimate_tokens


_PENDING_THREAD_HINT = (
    "La risoluzione precedente ha aperto un episodio senza popolare `situations_add`."
    " Rigenera lo stesso turno: ogni elemento introdotto dall'episodio e non risolto"
    " in questo turno DEVE comparire in `situations_add` come stringa breve."
    " Non cambiare il resto della risoluzione."
)


class TurnResolver:
    def __init__(self, *, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self.last_tokens: tuple[int, int, int] = (0, 0, 0)

    def resolve(self, request: NarrativeRequest) -> TurnResolution:
        result = self._complete(request)
        episode = request.episode
        if episode is None or episode.tier < 2 or result.situations_add:
            return result
        # An opening that declares nothing pending is not a thread: ask again once.
        first_tokens = self.last_tokens
        retry = self._complete(request, retry_hint=_PENDING_THREAD_HINT)
        self.last_tokens = tuple(  # type: ignore[assignment]
            a + b for a, b in zip(first_tokens, self.last_tokens)
        )
        return retry if retry.situations_add else result

    def _complete(
        self,
        request: NarrativeRequest,
        *,
        retry_hint: str = "",
    ) -> TurnResolution:
        system = self.llm.load_prompt("turn_resolve")
        rules = (request.story_rules or "").strip()
        if rules:
            system = (
                f"{system.rstrip()}\n\n"
                f"## Regole aggiuntive della storia\n{rules}\n"
            )
        if retry_hint:
            system = f"{system.rstrip()}\n\n## Correzione obbligatoria\n{retry_hint}\n"
        stall = (request.thread_hint or "").strip()
        if stall:
            system = f"{system.rstrip()}\n\n## Filo in stallo (suggerimento)\n{stall}\n"
        # story_rules / thread_hint live in the system prompt; omit from user JSON.
        payload = request.model_dump(mode="json")
        payload.pop("story_rules", None)
        payload.pop("thread_hint", None)
        import json

        user_prompt = json.dumps(payload, ensure_ascii=False)
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
