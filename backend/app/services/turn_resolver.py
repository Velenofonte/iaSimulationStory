from __future__ import annotations

from collections.abc import Callable

from app.config import settings
from app.models.narrative import NarrativeRequest, NarrativeTime
from app.models.turn import TurnResolution
from app.services.llm_client import LLMClient
from app.services.places import is_travel_intent
from app.services.token_estimate import estimate_tokens


_PENDING_THREAD_HINT = (
    "La risoluzione precedente ha aperto un episodio senza popolare `situations_add`."
    " Rigenera lo stesso turno: ogni elemento introdotto dall'episodio e non risolto"
    " in questo turno DEVE comparire in `situations_add` come oggetto"
    " `{ \"id\": \"slug_stabile\", \"summary\": \"fatto breve\" }`."
    " Non cambiare il resto della risoluzione."
)

_MISSING_TRAVEL_LOCATION_HINT = (
    "player_action e' uno spostamento fisico: `location` e' OBBLIGATORIO "
    "(id wiki o slug stabile del luogo in cui il PG e' ORA a fine turno). "
    "VIETATO lasciare location null. Non usare id di fazione o personaggio "
    "(es. adventurers-guild): usa un id di luogo (es. gilda-avventurieri, rovine-sud). "
    "Se il party del luogo lasciato non segue, `present` al nuovo posto "
    "(spesso []) con present_leave per chi resta dietro."
)


class TurnResolver:
    def __init__(self, *, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self.last_tokens: tuple[int, int, int] = (0, 0, 0)

    def resolve(self, request: NarrativeRequest) -> TurnResolution:
        result = self._complete(request)
        episode = request.episode
        if episode is not None and int(episode.tier) >= 2 and not result.situations_add:
            result = self._retry_once(
                request,
                result,
                _PENDING_THREAD_HINT,
                keep=lambda r: bool(r.situations_add),
            )
        if is_travel_intent(request.player_action) and not (result.location or "").strip():
            result = self._retry_once(
                request,
                result,
                _MISSING_TRAVEL_LOCATION_HINT,
                keep=lambda r: bool((r.location or "").strip()),
            )
        return result

    def _retry_once(
        self,
        request: NarrativeRequest,
        first: TurnResolution,
        hint: str,
        *,
        keep: Callable[[TurnResolution], bool],
    ) -> TurnResolution:
        first_tokens = self.last_tokens
        retry = self._complete(request, retry_hint=hint)
        self.last_tokens = tuple(  # type: ignore[assignment]
            a + b for a, b in zip(first_tokens, self.last_tokens)
        )
        return retry if keep(retry) else first

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
