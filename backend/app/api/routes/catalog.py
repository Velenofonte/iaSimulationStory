"""Catalog endpoints: stories, playable cast, races, fronts, eras."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    CharacterSheet,
    EraOption,
    FrontOption,
    PlayableCharacter,
    RaceOption,
    StorySummary,
)
from app.story.story_catalog import (
    get_playable_character,
    list_eras,
    list_fronts,
    list_playable_characters,
    list_races,
    list_stories,
)

router = APIRouter(tags=["catalog"])


@router.get("/stories", response_model=list[StorySummary])
def get_stories() -> list[StorySummary]:
    return [StorySummary.model_validate(item) for item in list_stories()]


@router.get("/stories/{story_id}/playable", response_model=list[PlayableCharacter])
def get_playable_characters(story_id: str) -> list[PlayableCharacter]:
    try:
        items = list_playable_characters(story_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [PlayableCharacter.model_validate(item) for item in items]


@router.get("/stories/{story_id}/playable/{character_id}", response_model=CharacterSheet)
def get_playable_character_sheet(story_id: str, character_id: str) -> CharacterSheet:
    try:
        data = get_playable_character(story_id, character_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CharacterSheet.model_validate(data)


@router.get("/stories/{story_id}/races", response_model=list[RaceOption])
def get_races(story_id: str) -> list[RaceOption]:
    try:
        items = list_races(story_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [RaceOption.model_validate(item) for item in items]


@router.get("/stories/{story_id}/fronts", response_model=list[FrontOption])
def get_fronts(story_id: str) -> list[FrontOption]:
    try:
        items = list_fronts(story_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [FrontOption.model_validate(item) for item in items]


@router.get("/stories/{story_id}/eras", response_model=list[EraOption])
def get_eras(story_id: str) -> list[EraOption]:
    try:
        items = list_eras(story_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [EraOption.model_validate(item) for item in items]
