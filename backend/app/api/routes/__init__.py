"""Aggregate API feature routers (mounted with prefix /api from main)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import saves

from . import catalog, gameplay, player_assets, sessions

router = APIRouter()
router.include_router(sessions.router)
router.include_router(catalog.router)
router.include_router(gameplay.router)
router.include_router(player_assets.router)

__all__ = ["router", "saves"]
