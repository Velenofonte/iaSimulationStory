"""Shared API dependencies (SaveManager singleton, session helpers)."""

from __future__ import annotations

from fastapi import HTTPException

from app.application.session_context import SessionServices, build_session_services
from app.models import GameState
from app.persistence.save_manager import SaveManager

saves = SaveManager()


def require_state(session_id: str) -> GameState:
    try:
        return saves.load_game_state(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def require_session(session_id: str) -> tuple[GameState, SessionServices]:
    state = require_state(session_id)
    try:
        svc = build_session_services(session_id, saves=saves)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return state, svc


def turns_until(every_n: int, since: int) -> int:
    return max(0, every_n - since)
