from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.game_state import (
    NpcKnowledgeFact,
    OffscreenCharacter,
    coerce_fact_list,
    coerce_id_list,
    coerce_npc_knowledge_upsert,
    coerce_present_leave,
)


class CharacterPresentUpdate(BaseModel):
    location: str | None = None
    mood: str | None = None
    relationship_delta: int | None = None


class LocationPresentUpdate(BaseModel):
    objects: list[str] = Field(default_factory=list)
    atmosphere: str | None = None
    events: list[str] = Field(default_factory=list)

    @staticmethod
    def _coerce_str_list(v: Any) -> list[str]:
        """LLM spesso manda dict {nome: descrizione} al posto di list[str]."""
        if v is None:
            return []
        if isinstance(v, str):
            s = v.strip()
            return [s] if s else []
        if isinstance(v, dict):
            out: list[str] = []
            for key, val in v.items():
                k = str(key).strip()
                if isinstance(val, dict):
                    # Nested: {"gilda": {"bancone": "..."}} → "gilda: bancone: ..."
                    inner = "; ".join(
                        f"{ik}: {iv}".strip(": ")
                        for ik, iv in val.items()
                        if str(iv).strip()
                    )
                    item = f"{k}: {inner}" if inner else k
                elif val is None or (isinstance(val, str) and not val.strip()):
                    item = k
                else:
                    item = f"{k}: {val}".strip() if k else str(val).strip()
                if item:
                    out.append(item)
            return out
        if isinstance(v, list):
            out = []
            for item in v:
                if isinstance(item, str):
                    s = item.strip()
                    if s:
                        out.append(s)
                elif isinstance(item, dict):
                    # [{name/id: ..., desc: ...}] o un solo entry dict
                    name = item.get("name") or item.get("id") or item.get("oggetto")
                    desc = item.get("description") or item.get("desc") or item.get("text")
                    if name and desc:
                        out.append(f"{name}: {desc}")
                    elif name:
                        out.append(str(name).strip())
                    else:
                        # flatten semplice
                        parts = [f"{k}: {val}" for k, val in item.items() if val is not None]
                        if parts:
                            out.append("; ".join(parts))
                elif item is not None:
                    s = str(item).strip()
                    if s:
                        out.append(s)
            return out
        s = str(v).strip()
        return [s] if s else []

    @field_validator("objects", "events", mode="before")
    @classmethod
    def _coerce_object_lists(cls, v: Any) -> list[str]:
        return cls._coerce_str_list(v)


class FrontImpact(BaseModel):
    front_id: str
    intent_id: str
    effect: Literal["null", "distort", "block"] | None = "null"
    evidence: str | None = None
    flags_set: dict[str, bool] | None = Field(
        default=None,
        description="Flag arco da impostare (es. carne_intact: false).",
    )


class PresentReviewResult(BaseModel):
    player_location: str | None = Field(
        default=None,
        description=(
            "Luogo fisico ATTUALE del giocatore. Aggiorna se e' cambiato "
            "(es. grotta-presso-e-rantel, non lasciare e-rantel se e' uscito dalla citta')."
        ),
    )
    time: str | None = Field(
        default=None,
        description="IGNORATO: l'orologio e' gestito solo dal codice (day/minutes).",
    )
    characters_active: list[str] = Field(
        default_factory=list,
        description=(
            "OBBLIGATORIO ogni review: lista COMPLETA sostitutiva degli NPC "
            "fisicamente presenti ORA con il giocatore (MAI il PG). [] se e' solo. "
            "Mai omettere."
        ),
    )

    @field_validator("characters_active", mode="before")
    @classmethod
    def _coerce_characters(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v] if v.strip() else []
        out: list[str] = []
        for item in v:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("id") or item.get("role")
                if name:
                    out.append(str(name).strip())
            else:
                s = str(item).strip()
                if s:
                    out.append(s)
        return list(dict.fromkeys(out))

    character_updates: dict[str, CharacterPresentUpdate] = Field(default_factory=dict)
    location_updates: dict[str, LocationPresentUpdate] = Field(default_factory=dict)
    situations_add: list[NpcKnowledgeFact] = Field(
        default_factory=list,
        description=(
            "Memoria a medio termine: {id, summary}. Stesso id = aggiorna summary; "
            "id nuovo = nuovo filo. Non micro-saluti; non solo catastrofi wiki."
        ),
    )
    situations_remove: list[str] = Field(
        default_factory=list,
        description=(
            "Ids di situations del game state da chiudere (known_ids.situations). "
            "Non rimuovere stato missioni/registri aperti solo perche' dettagliato."
        ),
    )
    npc_knowledge_upsert: dict[str, list[NpcKnowledgeFact]] = Field(
        default_factory=dict,
        description=(
            "Conoscenza per-NPC: riusa id esistenti per aggiornare summary, "
            "oppure crea id nuovi per fatti nuovi. Formato "
            '{ "npc_id": [{"id": "slug", "summary": "..."}] }.'
        ),
    )
    present_leave: dict[str, OffscreenCharacter] = Field(
        default_factory=dict,
        description=(
            "NPC che lasciano la scena: {id: {where, reason}}. "
            "Usali quando characters_active non li include piu' ma restano "
            "richiamabili (altra stanza, incarico, ecc.)."
        ),
    )
    front_impacts: list[FrontImpact] = Field(
        default_factory=list,
        description=(
            "Impatti sull'arco attivo: null|distort|block rispetto a un intent_id di strato 2. "
            "Per distruggere Carne: block pressure_village con flags_set.carne_intact=false."
        ),
    )
    # Chiavi libere nel game_state.extra (nuove o aggiornate)
    extra_set: dict[str, Any] = Field(default_factory=dict)
    extra_remove: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"

    @field_validator(
        "front_impacts",
        "extra_remove",
        mode="before",
    )
    @classmethod
    def _coerce_none_lists(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("situations_add", mode="before")
    @classmethod
    def _coerce_situations_add(cls, v: Any) -> list[NpcKnowledgeFact]:
        if v is None:
            return []
        return coerce_fact_list(v)

    @field_validator("situations_remove", mode="before")
    @classmethod
    def _coerce_situations_remove(cls, v: Any) -> list[str]:
        if v is None:
            return []
        return coerce_id_list(v)

    @field_validator("character_updates", "extra_set", mode="before")
    @classmethod
    def _coerce_none_dicts(cls, v: Any) -> Any:
        return {} if v is None else v

    @field_validator("npc_knowledge_upsert", mode="before")
    @classmethod
    def _coerce_npc_knowledge(cls, v: Any) -> dict[str, list[NpcKnowledgeFact]]:
        return coerce_npc_knowledge_upsert(v)

    @field_validator("present_leave", mode="before")
    @classmethod
    def _coerce_present_leave(cls, v: Any) -> dict[str, OffscreenCharacter]:
        return coerce_present_leave(v)

    @field_validator("location_updates", mode="before")
    @classmethod
    def _coerce_location_updates(cls, v: Any) -> Any:
        """LLM spesso scrive stringhe o chiavi IT (atmosfera) invece di LocationPresentUpdate."""
        if v is None:
            return {}
        if not isinstance(v, dict):
            return {}

        def _map_loc_dict(raw: dict[str, Any]) -> dict[str, Any]:
            mapped = dict(raw)
            if "atmosfera" in mapped and "atmosphere" not in mapped:
                mapped["atmosphere"] = mapped.pop("atmosfera")
            if "oggetti" in mapped and "objects" not in mapped:
                mapped["objects"] = mapped.pop("oggetti")
            if "eventi" in mapped and "events" not in mapped:
                mapped["events"] = mapped.pop("eventi")
            return mapped

        field_aliases = {"atmosfera", "atmosphere", "objects", "oggetti", "events", "eventi"}
        keys_lower = {str(k).casefold() for k in v}
        # Formato errato: {"atmosfera": "testo...", "oggetti": [...]} senza id luogo
        if keys_lower <= field_aliases or (
            keys_lower & field_aliases and not any(isinstance(x, dict) for x in v.values())
        ):
            return {"_scene": _map_loc_dict(v)}

        out: dict[str, Any] = {}
        for key, val in v.items():
            if isinstance(val, str):
                out[str(key)] = {"atmosphere": val}
            elif isinstance(val, dict):
                out[str(key)] = _map_loc_dict(val)
            elif val is None:
                continue
            else:
                out[str(key)] = val
        return out


class EntityCreate(BaseModel):
    type: Literal["character", "party", "location", "faction"]
    id: str
    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class CharacterConsolidationUpdate(BaseModel):
    memories_add: list[str] = Field(default_factory=list)
    memories_remove: list[str] = Field(default_factory=list)
    spells_add: list[str] = Field(default_factory=list)
    relationship: int | None = None
    relationship_summary_add: list[str] = Field(
        default_factory=list,
        description=(
            "Riassunto denso degli incontri col PG da appendere in "
            "'Relazione col giocatore' (non log di turni)."
        ),
    )
    open_threads_add: list[str] = Field(default_factory=list)
    open_threads_remove: list[str] = Field(default_factory=list)
    location: str | None = None
    party_id: str | None = None
    promote_tier: Literal["growing", "canonical"] | None = None
    # Sezioni wiki arbitrarie: {"Reputazione": ["temuto a E-Rantel"], "Equipaggiamento": ["..."]}
    sections_add: dict[str, list[str]] = Field(default_factory=dict)


class WikiPlaceUpdate(BaseModel):
    """Aggiornamenti duraturi a luoghi / nazioni / mondo."""
    events_add: list[str] = Field(default_factory=list)
    tensions_add: list[str] = Field(default_factory=list)
    # Sezioni wiki arbitrarie (nascono se non esistono)
    sections_add: dict[str, list[str]] = Field(default_factory=dict)


_CHAR_UPDATE_KEYS = {
    "memories_add",
    "memories_remove",
    "spells_add",
    "open_threads_add",
    "open_threads_remove",
    "relationship",
    "relationship_summary_add",
    "location",
    "party_id",
    "promote_tier",
    "sections_add",
}


class ConsolidationReviewResult(BaseModel):
    create_entities: list[EntityCreate] = Field(default_factory=list)
    character_updates: dict[str, CharacterConsolidationUpdate] = Field(default_factory=dict)
    location_updates: dict[str, WikiPlaceUpdate] = Field(default_factory=dict)
    world_updates: dict[str, WikiPlaceUpdate] = Field(default_factory=dict)
    state_cleanup: list[str] = Field(default_factory=list)
    party_active: str | None = None

    @field_validator("character_updates", mode="before")
    @classmethod
    def _coerce_character_updates(cls, v: Any) -> Any:
        """Accetta il formato piatto errato dell'LLM:
        {"player_id": "prova", "memories_add": [...], ...}
        → {"prova": {"memories_add": [...], ...}}.
        """
        if not isinstance(v, dict) or not v:
            return v
        flat_keys = _CHAR_UPDATE_KEYS & set(v.keys())
        if not flat_keys:
            return v
        player_key = v.get("player_id") or v.get("id") or v.get("name")
        if not isinstance(player_key, str) or not player_key.strip():
            player_key = "player"
        else:
            player_key = player_key.strip()
        update = {k: v[k] for k in flat_keys}
        return {player_key: update}
