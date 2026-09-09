from typing import Any

from pydantic import BaseModel, Field, field_validator, model_serializer


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
    "contesto di continuita' per TE — un NPC li conosce solo se rientra "
    "nelle condizioni 1-3 di Coerenza, non automaticamente"
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
    situations: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def _serialize_with_situations_note(self, serializer):
        """Wrap situations for LLM dumps: note + items (Python API stays list[str])."""
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
