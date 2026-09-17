"""Create / bootstrap a play session (wiki clone, character, arc/era seed)."""

from __future__ import annotations

from fastapi import HTTPException

from app.api.schemas import SessionCreateRequest, SessionResponse
from app.application.session_context import build_session_services
from app.llm.llm_client import LLMClient
from app.persistence.save_manager import SaveManager
from app.player.character_create import (
    extract_spells_from_body,
    generate_custom_player_sheet,
)
from app.story.era_loader import EraLoader
from app.story.story_catalog import (
    list_playable_characters,
    list_races,
    load_story_meta,
)
from app.wiki.wiki_writer import WikiWriter


def create_session(saves: SaveManager, payload: SessionCreateRequest) -> SessionResponse:
    try:
        meta = load_story_meta(payload.story_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    location = (payload.start_location or str(meta.get("start_location") or "e-rantel")).strip()
    player_name = payload.player_name.strip() or "Avventuriero"
    character_id: str | None = None
    race = (payload.race or "").strip() or None

    if payload.origin == "lore":
        playable = {p["id"]: p for p in list_playable_characters(payload.story_id)}
        cid = (payload.character_id or "").strip()
        if not cid or cid not in playable:
            raise HTTPException(
                status_code=400,
                detail="character_id obbligatorio e deve essere un personaggio playable",
            )
        character_id = cid
        player_name = playable[cid]["name"]
    else:
        character_id = WikiWriter.player_id(player_name)
        if payload.race:
            race_ids = {r["id"] for r in list_races(payload.story_id)}
            if race and race not in race_ids:
                raise HTTPException(status_code=400, detail=f"Razza sconosciuta: {race}")

    try:
        state = saves.create_session(
            player_name,
            start_location=location,
            story_id=payload.story_id,
            character_id=character_id,
            origin=payload.origin,
            race=race,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    svc = build_session_services(state.session_id, saves=saves, story_id=payload.story_id)
    pid = state.player.resolved_character_id()

    if payload.origin == "lore":
        try:
            svc.wiki.bind_as_player(pid, location=location)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        svc.wiki.ensure_spellbook(player_name, character_id=pid)
    else:
        details = (payload.details or "").strip()
        if race or details:
            llm = LLMClient()
            _meta, body = generate_custom_player_sheet(
                llm,
                story_id=payload.story_id,
                name=player_name,
                race=race or "human",
                details=details,
                location=location,
                character_id=pid,
            )
            svc.wiki.write_player_sheet(
                character_id=pid,
                name=player_name,
                location=location,
                body=body,
                race=race,
            )
            spells = extract_spells_from_body(body)
            svc.wiki.ensure_spellbook(player_name, character_id=pid)
            if spells:
                svc.wiki.track_spells(player_name, spells, character_id=pid)
        else:
            svc.wiki.ensure_player(player_name, location, character_id=pid)
            svc.wiki.ensure_spellbook(player_name, character_id=pid)

    if payload.start_mode == "era":
        era_id = (payload.era_id or "").strip()
        if not era_id:
            era_id = str(meta.get("default_era") or "holy_kingdom").strip()
        if era_id:
            try:
                if not payload.start_location:
                    era_def = EraLoader(story_id=payload.story_id).load(era_id)
                    state.player.location = era_def.start_location
                svc.story.seed_era(state, era_id, activate_entry=True, fire_start=True)
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        saves.save_game_state(state)
    elif payload.start_mode == "arc":
        front_id = (payload.front_id or meta.get("default_front") or "").strip()
        if front_id:
            try:
                svc.fronts.activate(state, str(front_id))
            except FileNotFoundError:
                pass
        saves.save_game_state(state)
    elif payload.start_mode == "free":
        front_id = (payload.front_id or "").strip()
        if front_id:
            try:
                svc.fronts.seed_world_after_arc(state, str(front_id))
            except FileNotFoundError:
                pass
            saves.save_game_state(state)

    svc.story.seed_player_lens(state)
    saves.save_game_state(state)
    saves.set_active_session(state.session_id)
    return SessionResponse(
        session_id=state.session_id,
        state=state,
        messages=saves.load_all_chat(state.session_id),
    )
