from typing import Any

from pydantic import BaseModel, Field, field_validator, model_serializer

from app.models.game_state import NpcKnowledgeFact, coerce_fact_list


def split_spell_line(line: str) -> tuple[str, str]:
    """Split 'Name — desc' tolerating em/en/hyphen dashes."""
    raw = line.strip().lstrip("-").strip()
    if not raw:
        return "", ""
    for sep in ("—", "–", " − ", " - ", "-"):
        if sep not in raw:
            continue
        name, desc = raw.split(sep, 1)
        name, desc = name.strip(), desc.strip()
        if name and (sep != "-" or len(name) < 40):
            return name, desc
    return raw, ""


SITUATIONS_EPISTEMIC_NOTE = (
    "NARRATOR_ONLY: continuita' per TE, non conoscenza NPC. "
    "Usa un fatto solo se e' sulla lente dell'NPC "
    "(Sa / Relazione / knowledge) o detto in presenza / su documento"
)

class NarrativeTime(BaseModel):
    bucket: str = Field(
        description="istantanea|breve|media|lunga|riposo (alias en: short/instant/…); range allargati per far avanzare l'arco",
    )
    minutes: int | None = Field(
        default=None,
        description="Minuti nel range del bucket; null per riposo o midpoint",
    )

    @field_validator("bucket", mode="before")
    @classmethod
    def _strip_bucket(cls, v: object) -> str:
        return str(v or "").strip()


class NarrativeSpell(BaseModel):
    name: str
    description: str = ""

    @classmethod
    def from_loose(cls, value: object) -> "NarrativeSpell":
        if isinstance(value, NarrativeSpell):
            return value
        if isinstance(value, dict):
            return cls.model_validate(value)
        name, desc = split_spell_line(str(value or ""))
        return cls(name=name, description=desc)


class NarrativeReply(BaseModel):
    """Structured narrator output: user-facing text + clock (never mixed into text)."""

    text: str = Field(description="Narrativa in italiano da mostrare al giocatore")
    time: NarrativeTime
    location: str | None = Field(
        default=None,
        description=(
            "Id luogo ATTUALE del giocatore se e' cambiato in questa scena "
            "(es. carne, tob-forest, e-rantel); null se invariato"
        ),
    )
    present: list[str] | None = Field(
        default=None,
        description=(
            "Lista COMPLETA sostitutiva degli NPC fisicamente presenti ORA con il PG. "
            "null = invariata; [] = il PG e' solo; nomi/ruoli gia' in scena (no nomi nuovi inventati)."
        ),
    )
    spells: list[NarrativeSpell] = Field(default_factory=list)

    @field_validator("spells", mode="before")
    @classmethod
    def _coerce_spells(cls, v: object) -> list:
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        out: list = []
        for item in v:
            spell = NarrativeSpell.from_loose(item)
            if spell.name:
                out.append(spell)
        return out

    @field_validator("present", mode="before")
    @classmethod
    def _coerce_present(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, str):
            v = [v] if v.strip() else []
        if not isinstance(v, list):
            return None
        out: list[str] = []
        for item in v:
            if isinstance(item, dict):
                name = item.get("name") or item.get("id") or item.get("role")
                if name:
                    out.append(str(name).strip())
            else:
                s = str(item or "").strip()
                if s:
                    out.append(s)
        # de-dupe preserve order
        return list(dict.fromkeys(out))

    @field_validator("text", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> str:
        return str(v or "").strip()



class NarrativeChatTurn(BaseModel):
    role: str
    content: str


class NarrativeWorldPage(BaseModel):
    id: str
    name: str
    excerpt: str


class NarrativeCanonFacts(BaseModel):
    location: str
    time: str
    present: list[str] = Field(default_factory=list)
    offscreen: list[str] = Field(
        default_factory=list,
        description="NPC fuori scena ma richiamabili: 'id — where: reason'",
    )
    situations: list[NpcKnowledgeFact] = Field(default_factory=list)
    known_ids: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Registro id riusabili: situations [{id,summary}] + "
            "npc_knowledge {npc_id: [{id,summary}]}"
        ),
    )
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("situations", mode="before")
    @classmethod
    def _coerce_situations(cls, v: Any) -> list[NpcKnowledgeFact]:
        return coerce_fact_list(v)

    @model_serializer(mode="wrap")
    def _serialize_with_situations_note(self, serializer):
        """Wrap situations for LLM dumps: note + {id, summary} items."""
        data = serializer(self)
        items = list(data.get("situations") or [])
        data["situations"] = {
            "note": SITUATIONS_EPISTEMIC_NOTE,
            "items": items,
        }
        return data


class NarrativeSpellEntry(BaseModel):
    name: str
    description: str = ""


class Episode(BaseModel):
    """Ambient episode mandate from the episode director (Pass 1 + Pass 2)."""

    tier: int = 0
    tier_label: str = ""
    kind: str = ""
    exposure: str = "low"
    witnesses: list[str] = Field(default_factory=list)
    no_auto_damage: bool = True
    must_not_resolve: bool = True
    opens_thread: bool = Field(
        default=True,
        description="True se l'episodio apre un filo da tracciare in situations (tier>=2)",
    )


class NarrativeRequest(BaseModel):
    """Structured context sent to the narrator LLM (user message = this JSON)."""

    canon_facts: NarrativeCanonFacts
    active_arc: str = Field(
        default="",
        description="Slice dell'arco/front attivo (beat correnti); vuoto se nessuno",
    )
    world_pages: list[NarrativeWorldPage] = Field(default_factory=list)
    character_cards: list[str] = Field(default_factory=list)
    spellbook: list[NarrativeSpellEntry] = Field(
        default_factory=list,
        description="Incantesimi noti del giocatore (spellbook separato dalla scheda)",
    )
    chat_recent: list[NarrativeChatTurn] = Field(default_factory=list)
    player_action: str
    stance: str = Field(
        default="action",
        description="action|passive|wait — wait = continua/attende fino a una svolta",
    )
    story_context: str = Field(
        default="",
        description="Genere/tono dalla meta della storia; vuoto se assente",
    )
    story_rules: str = Field(
        default="",
        description="Regole di setting iniettate (stories/<id>/prompts/episode.md); vuoto se assente",
    )
    episode: Episode | None = Field(
        default=None,
        description="Mandato episodio ambient; null se nessun evento questo turno",
    )
    notoriety_slice: str = Field(
        default="",
        description="Slice compatta di notorieta' / etichette / scarto; vuoto se assente",
    )
    scale_bands: list[str] = Field(
        default_factory=list,
        description="Id bande di scala del mondo dal pack (opachi per il motore)",
    )
    thread_hint: str = Field(
        default="",
        description="Suggerimento resolver se un filo ripete senza progresso; vuoto se assente",
    )
