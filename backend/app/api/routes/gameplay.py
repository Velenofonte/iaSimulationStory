"""Gameplay endpoints: chat turn and end-scene review."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import deps
from app.api.deps import require_session, require_state, turns_until
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    EndSceneRequest,
    EndSceneResponse,
)
from app.config import settings
from app.models import ChatMessage, GameState
from app.turn.chat_turn import process_chat_turn

router = APIRouter(tags=["gameplay"])


@router.get("/state/{session_id}", response_model=GameState)
def get_state(session_id: str) -> GameState:
    state = require_state(session_id)
    deps.saves.set_active_session(session_id)
    return state


@router.get("/chat/{session_id}", response_model=list[ChatMessage])
def get_chat(session_id: str) -> list[ChatMessage]:
    require_state(session_id)
    return deps.saves.load_all_chat(session_id)


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    state, svc = require_session(payload.session_id)
    result = process_chat_turn(svc, state, payload.message)
    deps.saves.set_active_session(payload.session_id)
    return ChatResponse(
        reply=result.reply,
        state=result.state,
        present_review_ran=result.present_review_ran,
        consolidation_ran=result.consolidation_ran,
        turns_until_present_review=turns_until(
            settings.present_review_every_n, result.state.turns_since_present_review
        ),
        turns_until_consolidation=turns_until(
            settings.consolidate_every_n, result.state.turns_since_consolidation
        ),
        input_tokens=result.input_tokens,
        input_tokens_system=result.input_tokens_system,
        input_tokens_user=result.input_tokens_user,
        input_tokens_cached=result.input_tokens_cached,
        review_tokens=result.review_tokens,
        can_undo=deps.saves.has_undo_checkpoint(payload.session_id),
        undo_count=deps.saves.undo_count(payload.session_id),
    )


@router.post("/end-scene", response_model=EndSceneResponse)
def end_scene(payload: EndSceneRequest) -> EndSceneResponse:
    state, svc = require_session(payload.session_id)
    svc.consequences.run_consolidation_review(state)
    lint_issues = svc.lint.run()
    state = deps.saves.load_game_state(payload.session_id)
    return EndSceneResponse(state=state, lint_issues=lint_issues)
