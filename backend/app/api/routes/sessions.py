"""Session lifecycle: create, list, get, delete, undo."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api import deps
from app.api.deps import require_state
from app.api.schemas import AppConfig, SessionCreateRequest, SessionResponse, SessionSummary
from app.application.create_session import create_session as bootstrap_session
from app.config import settings

router = APIRouter(tags=["sessions"])


@router.get("/config", response_model=AppConfig)
def get_config() -> AppConfig:
    return AppConfig(
        present_review_every_n=settings.present_review_every_n,
        consolidate_every_n=settings.consolidate_every_n,
    )


@router.get("/saves", response_model=list[SessionSummary])
def list_sessions() -> list[SessionSummary]:
    return [SessionSummary.model_validate(item) for item in deps.saves.list_sessions()]


@router.get("/saves/active", response_model=SessionSummary | None)
def get_active_session() -> SessionSummary | None:
    sid = deps.saves.get_active_session_id()
    if not sid:
        return None
    for item in deps.saves.list_sessions():
        if item["session_id"] == sid:
            return SessionSummary.model_validate(item)
    return None


@router.post("/session", response_model=SessionResponse)
def create_session(payload: SessionCreateRequest) -> SessionResponse:
    return bootstrap_session(deps.saves, payload)


@router.get("/session/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    state = require_state(session_id)
    deps.saves.set_active_session(session_id)
    return SessionResponse(
        session_id=session_id,
        state=state,
        messages=deps.saves.load_all_chat(session_id),
        can_undo=deps.saves.has_undo_checkpoint(session_id),
        undo_count=deps.saves.undo_count(session_id),
    )


@router.delete("/session/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    try:
        deps.saves.delete_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "session_id": session_id}


@router.post("/session/{session_id}/undo-last-turn", response_model=SessionResponse)
def undo_last_turn(session_id: str) -> SessionResponse:
    """Ripristina lo snapshot pre-turno. Solo I/O — nessun LLM."""
    require_state(session_id)
    if not deps.saves.has_undo_checkpoint(session_id):
        raise HTTPException(status_code=409, detail="Nessun turno da annullare")
    try:
        state = deps.saves.restore_undo_checkpoint(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    deps.saves.set_active_session(session_id)
    count = deps.saves.undo_count(session_id)
    return SessionResponse(
        session_id=session_id,
        state=state,
        messages=deps.saves.load_all_chat(session_id),
        can_undo=count > 0,
        undo_count=count,
    )


@router.get("/session/{session_id}/can-undo")
def can_undo_turn(session_id: str) -> dict[str, bool | int]:
    require_state(session_id)
    count = deps.saves.undo_count(session_id)
    return {"can_undo": count > 0, "undo_count": count}
