from app.config import settings
from app.models import CharacterCard
from app.services.token_estimate import estimate_tokens, fit_text


# Legacy section order (used when card_budget_* == 0 for non-regression).
_LEGACY_SECTION_ORDER = (
    "Personalita",
    "Personalità",
    "Aspetto fisico",
    "Allineamento",
    "Obiettivo",
    "Obiettivi",
    "Piani attuali",
    "Capacita di combattimento",
    "Capacità di combattimento",
    "Skill / build YGGDRASIL",
    "Arti marziali",
    "Ki",
    "Equipaggiamento",
    "Knowledge scope",
    "Relazione col giocatore",
    "Memorie",
    "Open threads",
    "Titoli validi",
    "Stato nell'arco",
)

# Priority order when a per-tier budget is active.
_BUDGET_SECTION_PRIORITY = (
    "Knowledge scope",
    "Titoli validi",
    "Stato nell'arco",
    "Personalita",
    "Personalità",
    "Obiettivo",
    "Obiettivi",
    "Piani attuali",
    "Capacita di combattimento",
    "Capacità di combattimento",
    "Skill / build YGGDRASIL",
    "Equipaggiamento",
    "Arti marziali",
    "Ki",
    "Relazione col giocatore",
    "Memorie",
    "Open threads",
    "Aspetto fisico",
    "Allineamento",
)


_PLAYER_NARRATOR_ONLY_SECTIONS = frozenset({"Memorie", "Open threads"})
_PLAYER_NARRATOR_ONLY_LABEL = "SOLO NARRATORE, non conoscenza NPC"


class PromptBuilder:
    def build_prompt_card(self, card: CharacterCard, runtime: dict | None = None) -> str:
        runtime = runtime or {}
        lines = [
            f"ID: {card.id}",
            f"Nome: {card.name or card.id}",
            f"Tier: {card.tier}",
        ]
        if card.role:
            lines.append(f"Ruolo: {card.role}")
        if card.location:
            lines.append(f"Luogo: {card.location}")
        if card.faction:
            lines.append(f"Fazione: {card.faction}")

        sections = self._extract_sections(card.body)
        is_player = str(card.role or "").lower() == "player"

        def _section_line(key: str, text: str) -> str:
            if is_player and key in _PLAYER_NARRATOR_ONLY_SECTIONS:
                return f"{key} ({_PLAYER_NARRATOR_ONLY_LABEL}): {text}"
            return f"{key}: {text}"

        # Controlled player: full sheet, no section/budget cuts.
        if is_player:
            for key in _LEGACY_SECTION_ORDER:
                if key in sections:
                    lines.append(_section_line(key, sections[key]))
            if runtime.get("mood"):
                lines.append(f"Mood attuale: {runtime['mood']}")
            if runtime.get("relationship") is not None:
                lines.append(f"Relazione col giocatore: {runtime['relationship']}")
            return "\n".join(lines)

        section_cap = settings.card_section_chars
        budget = self._tier_budget(card.tier)

        if budget <= 0:
            for key in _LEGACY_SECTION_ORDER:
                if key in sections:
                    text = sections[key]
                    if section_cap > 0:
                        text = text[:section_cap]
                    lines.append(_section_line(key, text))
        else:
            header = "\n".join(lines)
            used = estimate_tokens(header)
            for key in _BUDGET_SECTION_PRIORITY:
                if key not in sections:
                    continue
                text = sections[key]
                if section_cap > 0:
                    text = text[:section_cap]
                candidate = _section_line(key, text)
                cost = estimate_tokens(candidate)
                if used + cost > budget:
                    remaining = budget - used
                    if remaining <= 0:
                        break
                    trimmed = fit_text(candidate, remaining)
                    if trimmed:
                        lines.append(trimmed)
                    break
                lines.append(candidate)
                used += cost

        if runtime.get("mood"):
            lines.append(f"Mood attuale: {runtime['mood']}")
        if runtime.get("relationship") is not None:
            lines.append(f"Relazione col giocatore: {runtime['relationship']}")
        return "\n".join(lines)

    def _tier_budget(self, tier: str) -> int:
        mapping = {
            "minimal": settings.card_budget_minimal,
            "growing": settings.card_budget_growing,
            "canonical": settings.card_budget_canonical,
        }
        return int(mapping.get(tier, 0) or 0)

    def _extract_sections(self, body: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        current = None
        buffer: list[str] = []
        for line in body.splitlines():
            if line.startswith("# "):
                if current:
                    sections[current] = "\n".join(buffer).strip()
                current = line[2:].strip()
                buffer = []
            else:
                buffer.append(line)
        if current:
            sections[current] = "\n".join(buffer).strip()
        return sections
