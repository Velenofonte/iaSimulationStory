from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.models import ChatMessage, GameState
from app.models.game_state import ArcTimelineResponse
from app.services.character_create import (
    extract_spells_from_body,
    generate_custom_player_sheet,
)
from app.services.chat_turn import process_chat_turn
from app.services.llm_client import LLMClient
from app.services.save_manager import SaveManager
from app.services.session_context import SessionServices, build_session_services
from app.services.story_catalog import (
    get_playable_character,
    list_fronts,
    list_playable_characters,
    list_races,
    list_stories,
    load_story_meta,
)
from app.services.wiki_writer import WikiWriter

router = APIRouter(prefix="/api")
saves = SaveManager()


class SessionCreateRequest(BaseModel):
    player_name: str = "Avventuriero"
    start_location: str | None = None
    story_id: str = "overlord"
    origin: Literal["lore", "custom"] = "custom"
    character_id: str | None = None
    race: str | None = None
    details: str = ""
    start_mode: Literal["arc", "free"] = "arc"
    front_id: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    state: GameState
    messages: list[ChatMessage] = Field(default_factory=list)
    can_undo: bool = False
    undo_count: int = 0


class SpellEntry(BaseModel):
    name: str
    description: str = ""


class CharacterSheet(BaseModel):
    id: str
    name: str
    role: str | None = None
    location: str | None = None
    race: str | None = None
    job: str | None = None
    affiliation: str | None = None
    residence: str | None = None
    level: str | int | None = None
    body: str = ""
    spells: list[SpellEntry] = Field(default_factory=list)


class SpellbookResponse(BaseModel):
    player_id: str
    spells: list[SpellEntry] = Field(default_factory=list)


class StorySummary(BaseModel):
    id: str
    name: str
    description: str = ""
    start_location: str = "e-rantel"
    default_front: str | None = None
    has_wiki: bool = False


class PlayableCharacter(BaseModel):
    id: str
    name: str
    summary: str = ""


class RaceOption(BaseModel):
    id: str
    name: str


class FrontOption(BaseModel):
    id: str
    name: str


class SessionSummary(BaseModel):
    session_id: str
    story_id: str = "overlord"
    story_name: str = "Overlord"
    player_name: str
    location: str
    time: str
    updated_at: str
    active: bool = False


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    state: GameState
    present_review_ran: bool = False
    consolidation_ran: bool = False
    turns_until_present_review: int = 0
    turns_until_consolidation: int = 0
    input_tokens: int = 0
    input_tokens_system: int = 0
    input_tokens_user: int = 0
    input_tokens_cached: int = 0
    review_tokens: int = 0
    can_undo: bool = False
    undo_count: int = 0


def _turns_until(every_n: int, since: int) -> int:
    return max(0, every_n - since)


def _require_state(session_id: str) -> GameState:
    try:
        return saves.load_game_state(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _require_session(session_id: str) -> tuple[GameState, SessionServices]:
    state = _require_state(session_id)
    try:
        svc = build_session_services(session_id, saves=saves)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return state, svc


class EndSceneRequest(BaseModel):
    session_id: str


class EndSceneResponse(BaseModel):
    state: GameState
    lint_issues: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    present_review_every_n: int
    consolidate_every_n: int


@router.get("/config", response_model=AppConfig)
def get_config() -> AppConfig:
    return AppConfig(
        present_review_every_n=settings.present_review_every_n,
        consolidate_every_n=settings.consolidate_every_n,
    )


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


@router.get("/saves", response_model=list[SessionSummary])
def list_sessions() -> list[SessionSummary]:
    return [SessionSummary.model_validate(item) for item in saves.list_sessions()]


@router.delete("/session/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    try:
        saves.delete_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "session_id": session_id}


@router.post("/session/{session_id}/undo-last-turn", response_model=SessionResponse)
def undo_last_turn(session_id: str) -> SessionResponse:
    """Ripristina lo snapshot pre-turno. Solo I/O — nessun LLM."""
    _require_state(session_id)
    if not saves.has_undo_checkpoint(session_id):
        raise HTTPException(status_code=409, detail="Nessun turno da annullare")
    try:
        state = saves.restore_undo_checkpoint(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    saves.set_active_session(session_id)
    count = saves.undo_count(session_id)
    return SessionResponse(
        session_id=session_id,
        state=state,
        messages=saves.load_all_chat(session_id),
        can_undo=count > 0,
        undo_count=count,
    )


@router.get("/session/{session_id}/can-undo")
def can_undo_turn(session_id: str) -> dict[str, bool | int]:
    _require_state(session_id)
    count = saves.undo_count(session_id)
    return {"can_undo": count > 0, "undo_count": count}


@router.get("/saves/active", response_model=SessionSummary | None)
def get_active_session() -> SessionSummary | None:
    sid = saves.get_active_session_id()
    if not sid:
        return None
    for item in saves.list_sessions():
        if item["session_id"] == sid:
            return SessionSummary.model_validate(item)
    return None


@router.post("/session", response_model=SessionResponse)
def create_session(payload: SessionCreateRequest) -> SessionResponse:
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

    svc = build_session_services(state.session_id, saves=saves)
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
            # Legacy / minimal: stub empty sheet
            svc.wiki.ensure_player(player_name, location, character_id=pid)
            svc.wiki.ensure_spellbook(player_name, character_id=pid)

    if payload.start_mode == "arc":
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

    saves.set_active_session(state.session_id)
    return SessionResponse(
        session_id=state.session_id,
        state=state,
        messages=saves.load_all_chat(state.session_id),
    )


@router.get("/session/{session_id}/sheet", response_model=CharacterSheet)
def get_player_sheet(session_id: str) -> CharacterSheet:
    state, svc = _require_session(session_id)
    pid = state.player.resolved_character_id()
    svc.wiki.ensure_player(state.player.name, state.player.location, character_id=pid)
    data = svc.wiki.read_character(pid)
    return CharacterSheet.model_validate(data)


@router.get("/session/{session_id}/spellbook", response_model=SpellbookResponse)
def get_spellbook(session_id: str) -> SpellbookResponse:
    state, svc = _require_session(session_id)
    pid = state.player.resolved_character_id()
    spells = svc.wiki.read_spellbook(state.player.name, character_id=pid)
    return SpellbookResponse(
        player_id=pid,
        spells=[SpellEntry.model_validate(s) for s in spells],
    )


@router.get("/session/{session_id}/arc-timeline", response_model=ArcTimelineResponse)
def get_arc_timeline(session_id: str) -> ArcTimelineResponse:
    state, svc = _require_session(session_id)
    # Catch up off-screen wiki only; defer presence fires for POST /chat narration
    fired = svc.fronts.sync_to_clock(state, for_display=True)
    if fired:
        saves.save_game_state(state)
    return svc.fronts.build_canon_timeline(state)


@router.get("/session/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    state = _require_state(session_id)
    saves.set_active_session(session_id)
    return SessionResponse(
        session_id=session_id,
        state=state,
        messages=saves.load_all_chat(session_id),
        can_undo=saves.has_undo_checkpoint(session_id),
        undo_count=saves.undo_count(session_id),
    )


@router.get("/state/{session_id}", response_model=GameState)
def get_state(session_id: str) -> GameState:
    state = _require_state(session_id)
    saves.set_active_session(session_id)
    return state


@router.get("/chat/{session_id}", response_model=list[ChatMessage])
def get_chat(session_id: str) -> list[ChatMessage]:
    _require_state(session_id)
    return saves.load_all_chat(session_id)


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    state, svc = _require_session(payload.session_id)
    result = process_chat_turn(svc, state, payload.message)
    saves.set_active_session(payload.session_id)
    return ChatResponse(
        reply=result.reply,
        state=result.state,
        present_review_ran=result.present_review_ran,
        consolidation_ran=result.consolidation_ran,
        turns_until_present_review=_turns_until(
            settings.present_review_every_n, result.state.turns_since_present_review
        ),
        turns_until_consolidation=_turns_until(
            settings.consolidate_every_n, result.state.turns_since_consolidation
        ),
        input_tokens=result.input_tokens,
        input_tokens_system=result.input_tokens_system,
        input_tokens_user=result.input_tokens_user,
        input_tokens_cached=result.input_tokens_cached,
        review_tokens=result.review_tokens,
        can_undo=saves.has_undo_checkpoint(payload.session_id),
        undo_count=saves.undo_count(payload.session_id),
    )


@router.post("/end-scene", response_model=EndSceneResponse)
def end_scene(payload: EndSceneRequest) -> EndSceneResponse:
    state, svc = _require_session(payload.session_id)
    svc.consequences.run_consolidation_review(state)
    lint_issues = svc.lint.run()
    state = saves.load_game_state(payload.session_id)
    return EndSceneResponse(state=state, lint_issues=lint_issues)
