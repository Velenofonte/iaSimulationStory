from __future__ import annotations

import re

from app.config import settings
from app.models import ChatMessage, GameState
from app.models.narrative import (
    NarrativeCanonFacts,
    NarrativeChatTurn,
    NarrativeRequest,
    NarrativeSpellEntry,
    NarrativeWorldPage,
)
from app.services.front_engine import FrontEngine
from app.services.game_clock import format_label
from app.services.narrative_stance import detect_stance
from app.services.prompt_builder import PromptBuilder
from app.services.save_manager import SaveManager
from app.services.story_catalog import build_story_context
from app.services.token_estimate import estimate_tokens, fill_by_priority, fit_text
from app.services.wiki_query import WikiQuery, build_world_excerpt
from app.services.wiki_writer import WikiWriter

_BRACKET_SPELL_RE = re.compile(r"\[([^\[\]]+)\]")


class NarrativeBudgetPolicy:
    """Trim NarrativeRequest lists until under a global token budget."""

    @staticmethod
    def apply(request: NarrativeRequest, budget: int) -> NarrativeRequest:
        if budget <= 0:
            return request

        core = NarrativeRequest(
            canon_facts=request.canon_facts,
            active_arc=request.active_arc,
            world_pages=[],
            character_cards=[],
            spellbook=[],
            chat_recent=[],
            player_action=request.player_action,
            stance=request.stance,
            story_context=request.story_context,
        )
        used = estimate_tokens(core.model_dump_json())
        remaining = budget - used
        if remaining <= 0:
            return core

        cards = fill_by_priority(
            list(request.character_cards),
            remaining,
            size_fn=estimate_tokens,
        )
        used += sum(estimate_tokens(c) for c in cards)
        remaining = budget - used

        chat = list(request.chat_recent)
        if remaining > 0:
            chat_rev = fill_by_priority(
                list(reversed(chat)),
                remaining,
                size_fn=lambda t: estimate_tokens(t.model_dump_json()),
            )
            chat = list(reversed(chat_rev))
            used += sum(estimate_tokens(t.model_dump_json()) for t in chat)
            remaining = budget - used
        else:
            chat = []

        world: list[NarrativeWorldPage] = []
        if remaining > 0:
            world = fill_by_priority(
                list(request.world_pages),
                remaining,
                size_fn=lambda p: estimate_tokens(p.model_dump_json()),
            )
            used += sum(estimate_tokens(p.model_dump_json()) for p in world)
            remaining = budget - used

        spells: list[NarrativeSpellEntry] = []
        if remaining > 0:
            spells = fill_by_priority(
                list(request.spellbook),
                remaining,
                size_fn=lambda s: estimate_tokens(s.model_dump_json()),
            )

        arc = request.active_arc
        probe = NarrativeRequest(
            canon_facts=request.canon_facts,
            active_arc=arc,
            world_pages=world,
            character_cards=cards,
            spellbook=spells,
            chat_recent=chat,
            player_action=request.player_action,
            stance=request.stance,
            story_context=request.story_context,
        )
        if estimate_tokens(probe.model_dump_json()) > budget and arc:
            overhead = estimate_tokens(probe.model_dump_json()) - estimate_tokens(arc)
            arc_budget = max(0, budget - overhead)
            arc = fit_text(arc, arc_budget)

        return NarrativeRequest(
            canon_facts=request.canon_facts,
            active_arc=arc,
            world_pages=world,
            character_cards=cards,
            spellbook=spells,
            chat_recent=chat,
            player_action=request.player_action,
            stance=request.stance,
            story_context=request.story_context,
        )


class NarrativeContextAssembler:
    def __init__(
        self,
        *,
        wiki: WikiQuery | None = None,
        wiki_writer: WikiWriter | None = None,
        fronts: FrontEngine | None = None,
        saves: SaveManager | None = None,
        prompts: PromptBuilder | None = None,
    ) -> None:
        self.wiki = wiki or WikiQuery()
        self.wiki_writer = wiki_writer or WikiWriter()
        self.prompts = prompts or PromptBuilder()
        self.saves = saves or SaveManager()
        self.fronts = fronts or FrontEngine(wiki=self.wiki_writer)

    def _active_arc_ids(self, state: GameState) -> list[str]:
        return [
            front_id
            for front_id, runtime in state.fronts.items()
            if runtime and runtime.status in {"active", "diverted"}
        ]

    def _append_character_card(
        self,
        *,
        character_id: str,
        state: GameState,
        active_arcs: list[str],
        cards: list[str],
        card_ids: set[str],
    ) -> None:
        cid = (character_id or "").strip()
        if not cid:
            return
        key = cid.lower()
        if key in card_ids:
            return
        card = self.wiki.load_character(cid, active_arc_ids=active_arcs)
        if not card:
            return
        runtime = state.characters.get(cid)
        runtime_dict = runtime.model_dump() if runtime else {}
        cards.append(self.prompts.build_prompt_card(card, runtime_dict))
        card_ids.add(str(card.id).lower())
        card_ids.add(key)

    def _build_character_cards(
        self, state: GameState, active_arcs: list[str]
    ) -> tuple[list[str], set[str]]:
        """Player sheet first (always), then present NPCs."""
        cards: list[str] = []
        card_ids: set[str] = set()
        player_id = state.player.resolved_character_id()
        self._append_character_card(
            character_id=player_id,
            state=state,
            active_arcs=active_arcs,
            cards=cards,
            card_ids=card_ids,
        )
        for character_id in state.characters_active:
            self._append_character_card(
                character_id=character_id,
                state=state,
                active_arcs=active_arcs,
                cards=cards,
                card_ids=card_ids,
            )
        return cards, card_ids

    def build_request(self, *, state: GameState, user_message: str) -> NarrativeRequest:
        active_arcs = self._active_arc_ids(state)
        pages = self.wiki.query(
            game_state=state,
            user_message=user_message,
            mode="scene",
            active_arc_ids=active_arcs,
        )
        seen_ids = {pid for pid, _, _ in pages}
        for cast_id in self.fronts.relevant_cast_wiki_ids(state):
            if len(pages) >= settings.wiki_page_cap:
                break
            if cast_id in seen_ids:
                continue
            path = self.wiki.resolve_id(cast_id)
            if not path or not path.exists():
                continue
            meta, body = self.wiki.read_page(path)
            card = self.wiki.load_character(cast_id, active_arc_ids=active_arcs)
            if card:
                meta = dict(card.metadata)
                body = card.body
            pages.append((cast_id, meta, body))
            seen_ids.add(cast_id)

        recent = self.saves.load_recent_chat(
            state.session_id, limit=settings.narrative_chat_messages
        )
        tempo = format_label(state.day, state.minutes)
        arc_slice = self.fronts.build_prompt_slice(state)

        cards, card_ids = self._build_character_cards(state, active_arcs)

        excerpt_cap = settings.world_excerpt_chars
        world_pages: list[NarrativeWorldPage] = []
        for entity_id, meta, body in pages:
            eid = str(entity_id).lower()
            if settings.narrative_dedup_world_cards and (
                eid in card_ids or str(meta.get("id", "")).lower() in card_ids
            ):
                continue
            excerpt = build_world_excerpt(
                body, excerpt_cap, entity_id=str(entity_id)
            )
            world_pages.append(
                NarrativeWorldPage(
                    id=str(entity_id),
                    name=str(meta.get("name", entity_id)),
                    excerpt=excerpt,
                )
            )

        raw_spells = self.wiki_writer.read_spellbook(
            state.player.name,
            character_id=state.player.resolved_character_id(),
        )
        spellbook = self._build_spellbook(raw_spells, user_message)
        chat_recent = self._compress_chat(recent)
        stance = detect_stance(user_message)

        request = NarrativeRequest(
            canon_facts=NarrativeCanonFacts(
                location=state.player.location,
                time=tempo,
                present=list(state.characters_active),
                situations=list(state.situations),
                extra=dict(state.extra),
            ),
            active_arc=arc_slice,
            world_pages=world_pages,
            character_cards=cards,
            spellbook=spellbook,
            chat_recent=chat_recent,
            player_action=user_message,
            stance=stance,
            story_context=build_story_context(state.story_id),
        )
        trimmed = NarrativeBudgetPolicy.apply(request, settings.narrative_token_budget)
        extracted = self.wiki.extract_entities_from_text(user_message)
        excerpt_lens = {p.id: len(p.excerpt or "") for p in trimmed.world_pages}
        lore_flags = []
        for p in trimmed.world_pages:
            if "adventurer" not in p.id.lower():
                continue
            ex = p.excerpt or ""
            lore_flags.append(
                f"{p.id}:Mithril={'Mithril' in ex}/Adamantite={'Adamantite' in ex}"
            )
        print(
            "[turn_context]"
            f" loc={state.player.location!r}"
            f" present={list(state.characters_active)!r}"
            f" extracted={extracted!r}"
            f" world_pages={[p.id for p in trimmed.world_pages]!r}"
            f" excerpt_chars={excerpt_lens!r}"
            f" lore={lore_flags!r}"
            f" cards={len(trimmed.character_cards)}"
            f" chat={len(trimmed.chat_recent)}"
            f" spells={len(trimmed.spellbook)}"
            f" arc={'yes' if trimmed.active_arc else 'no'}"
            f" stance={stance!r}"
        )
        return trimmed

    def build_render_cards(self, state: GameState) -> list[str]:
        """Character cards for post-presence / post-clock render pass."""
        active_arcs = self._active_arc_ids(state)
        cards, _ = self._build_character_cards(state, active_arcs)
        return cards

    def _build_spellbook(
        self, raw_spells: list[dict[str, str]], user_message: str
    ) -> list[NarrativeSpellEntry]:
        full = [
            NarrativeSpellEntry(name=s["name"], description=s.get("description") or "")
            for s in raw_spells
        ]
        if not settings.narrative_spellbook_on_demand:
            return full
        msg_lower = user_message.lower()
        needs_full = bool(_BRACKET_SPELL_RE.search(user_message))
        if not needs_full:
            for s in raw_spells:
                name = (s.get("name") or "").strip()
                if name and name.lower() in msg_lower:
                    needs_full = True
                    break
        if needs_full:
            return full
        return [NarrativeSpellEntry(name=s["name"], description="") for s in raw_spells]

    def _compress_chat(self, recent: list[ChatMessage]) -> list[NarrativeChatTurn]:
        old_cap = settings.narrative_chat_old_char_cap
        turns: list[NarrativeChatTurn] = []
        n = len(recent)
        keep_full_from = max(0, n // 2) if old_cap > 0 else 0
        for i, m in enumerate(recent):
            content = m.content
            if old_cap > 0 and i < keep_full_from and len(content) > old_cap:
                content = content[:old_cap].rstrip() + "…"
            turns.append(NarrativeChatTurn(role=m.role, content=content))
        return turns
