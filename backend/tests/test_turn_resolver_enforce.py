"""A tier>=2 opening must declare what stays pending, or it is regenerated once."""

from app.models.narrative import (
    Episode,
    NarrativeCanonFacts,
    NarrativeRequest,
    NarrativeTime,
)
from app.models.turn import TurnResolution
from app.services.turn_resolver import TurnResolver


class _StubLLM:
    def __init__(self, results: list[TurnResolution]) -> None:
        self.results = list(results)
        self.systems: list[str] = []
        self.last_usage = None

    def load_prompt(self, name: str) -> str:
        return "SYSTEM"

    def complete_json(self, *, system, user, schema, model=None, temperature=0.0):
        self.systems.append(system)
        return self.results.pop(0)


def _resolution(situations: tuple[str, ...] = ()) -> TurnResolution:
    return TurnResolution(
        time=NarrativeTime(bucket="istantanea", minutes=2),
        scene_brief=["un delta"],
        situations_add=list(situations),
    )


def _request(tier: int) -> NarrativeRequest:
    return NarrativeRequest(
        canon_facts=NarrativeCanonFacts(location="avamposto", time="Giorno 1 · mattina"),
        player_action="aspetto",
        stance="wait",
        episode=Episode(tier=tier, tier_label="gancio", kind="arrival", exposure="low"),
    )


def test_episode_without_pending_thread_is_regenerated() -> None:
    stub = _StubLLM([_resolution(), _resolution(("figura incatenata non identificata",))])
    out = TurnResolver(llm=stub).resolve(_request(3))
    assert [s.summary for s in out.situations_add] == ["figura incatenata non identificata"]
    assert len(stub.systems) == 2
    assert "Correzione obbligatoria" in stub.systems[1]


def test_low_tier_episode_is_not_regenerated() -> None:
    stub = _StubLLM([_resolution()])
    out = TurnResolver(llm=stub).resolve(_request(0))
    assert out.situations_add == []
    assert len(stub.systems) == 1


def test_thread_hint_injected_into_system() -> None:
    stub = _StubLLM([_resolution(("ok",))])
    req = _request(2)
    req.thread_hint = "Il PG insiste sullo stesso filo (medaglione)."
    TurnResolver(llm=stub).resolve(req)
    assert "Filo in stallo" in stub.systems[0]
    assert "medaglione" in stub.systems[0]


def test_retry_without_thread_keeps_first_resolution() -> None:
    stub = _StubLLM([_resolution(), _resolution()])
    out = TurnResolver(llm=stub).resolve(_request(4))
    assert out.situations_add == []
    assert len(stub.systems) == 2
