"""Present-review must not re-admit cast cleared by the latest chat present."""

from app.episodes.consequence_engine import ConsequenceEngine
from app.models import ChatMessage, GameState, PlayerState, PresentReviewResult


def test_clamp_present_review_does_not_expand_past_last_chat_present() -> None:
    result = PresentReviewResult(
        characters_active=["capitano_vex", "arciere", "guardia"],
    )
    recent = [
        ChatMessage(role="user", content="mi guardo intorno", present=[]),
        ChatMessage(role="assistant", content="Il camminatoio e' deserto.", present=[]),
    ]
    ConsequenceEngine.clamp_present_review_to_chat(result, recent)
    assert result.characters_active == []


def test_clamp_present_review_may_drop_subset() -> None:
    result = PresentReviewResult(characters_active=["kael"])
    recent = [
        ChatMessage(
            role="assistant",
            content="Kael e Oste sono ancora qui.",
            present=["kael", "oste"],
        ),
    ]
    ConsequenceEngine.clamp_present_review_to_chat(result, recent)
    assert result.characters_active == ["kael"]


def test_clamp_present_review_noop_without_assistant_chat() -> None:
    result = PresentReviewResult(characters_active=["kael"])
    ConsequenceEngine.clamp_present_review_to_chat(result, [])
    assert result.characters_active == ["kael"]


def test_apply_present_review_clamps_via_recent() -> None:
    state = GameState(
        session_id="s",
        player=PlayerState(location="sentiero"),
        characters_active=[],
    )
    result = PresentReviewResult(
        characters_active=["kael", "oste"],
    )
    recent = [
        ChatMessage(role="assistant", content="Sei solo.", present=[]),
    ]
    engine = ConsequenceEngine()
    engine.apply_present_review(state, result, recent=recent)
    assert state.characters_active == []
