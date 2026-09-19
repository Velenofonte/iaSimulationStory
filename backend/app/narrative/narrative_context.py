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
from app.story.front_engine import FrontEngine
from app.turn.game_clock import format_label
from app.narrative.narrative_stance import detect_stance
from app.narrative.prompt_builder import PromptBuilder
from app.persistence.save_manager import SaveManager
from app.player.id_registry import build_known_ids
from app.player.knowledge import known_ids, level
from app.turn.state_reducer import format_offscreen_lines
from app.story.story_catalog import build_story_context, load_story_episode_prompt
from app.story.story_engine import StoryEngine, epoch_overlay_ids
from app.episodes.episode_pack import load_episode_pack
from app.episodes.notoriety import to_prompt_slice as notoriety_prompt_slice
from app.narrative.token_estimate import estimate_tokens, fill_by_priority, fit_text
from app.player.places import infer_location_kind, place_ancestors
from app.wiki.wiki_query import WikiQuery, build_world_excerpt
from app.wiki.wiki_writer import WikiWriter

_BRACKET_SPELL_RE = re.compile(r"\[([^\[\]]+)\]")


class NarrativeBudgetPolicy:
    """Trim NarrativeRequest lists until under a global token budget."""

    @staticmethod
    def apply(request: NarrativeRequest, budget: int) -> NarrativeRequest:
        if budget <= 0:
            return request

        free_rules = request.story_rules or ""

        core = NarrativeRequest(
            canon_facts=request.canon_facts,
            active_arc=request.active_arc,
            story_so_far=request.story_so_far,
            world_pages=[],
            character_cards=[],
            spellbook=[],
            chat_recent=[],
            player_action=request.player_action,
            stance=request.stance,
            story_context=request.story_context,
            story_rules="",
            episode=request.episode,
            notoriety_slice="",
            scale_bands=[],
            thread_hint="",
        )
        used = estimate_tokens(core.model_dump_json())
        remaining = budget - used
        if remaining <= 0:
            return core.model_copy(
                update={
                    "story_rules": free_rules,
                    "notoriety_slice": request.notoriety_slice,
                    "scale_bands": list(request.scale_bands),
                    "thread_hint": request.thread_hint,
                }
            )

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
        story_so_far = request.story_so_far
        probe = NarrativeRequest(
            canon_facts=request.canon_facts,
            active_arc=arc,
            story_so_far=story_so_far,
            world_pages=world,
            character_cards=cards,
            spellbook=spells,
            chat_recent=chat,
            player_action=request.player_action,
            stance=request.stance,
            story_context=request.story_context,
            story_rules="",
            episode=request.episode,
            notoriety_slice="",
            scale_bands=[],
            thread_hint="",
        )
        if estimate_tokens(probe.model_dump_json()) > budget and arc:
            overhead = estimate_tokens(probe.model_dump_json()) - estimate_tokens(arc)
            arc_budget = max(0, budget - overhead)
            arc = fit_text(arc, arc_budget)
        if estimate_tokens(probe.model_dump_json()) > budget and story_so_far:
            overhead = estimate_tokens(probe.model_dump_json()) - estimate_tokens(story_so_far)
            so_far_budget = max(0, budget - overhead)
            story_so_far = fit_text(story_so_far, so_far_budget)

        return NarrativeRequest(
            canon_facts=request.canon_facts,
            active_arc=arc,
            story_so_far=story_so_far,
            world_pages=world,
            character_cards=cards,
            spellbook=spells,
            chat_recent=chat,
            player_action=request.player_action,
            stance=request.stance,
            story_context=request.story_context,
            story_rules=free_rules,
            episode=request.episode,
            notoriety_slice=request.notoriety_slice,
            scale_bands=list(request.scale_bands),
            thread_hint=request.thread_hint,
        )


class NarrativeContextAssembler:
    def __init__(
        self,
        *,
        wiki: WikiQuery | None = None,
        wiki_writer: WikiWriter | None = None,
        fronts: FrontEngine | None = None,
        story: StoryEngine | None = None,
        saves: SaveManager | None = None,
        prompts: PromptBuilder | None = None,
    ) -> None:
        self.wiki = wiki or WikiQuery()
        self.wiki_writer = wiki_writer or WikiWriter()
        self.prompts = prompts or PromptBuilder()
        self.saves = saves or SaveManager()
        self.fronts = fronts or FrontEngine(wiki=self.wiki_writer)
        self.story = story or StoryEngine(fronts=self.fronts, wiki=self.wiki_writer)

    def _active_arc_ids(self, state: GameState) -> list[str]:
        return epoch_overlay_ids(state)

    def _append_character_card(
        self,
        *,
        character_id: str,
        state: GameState,
        active_arcs: list[str],
        cards: list[str],
        card_ids: set[str],
        render: bool = False,
        roles: dict[str, str] | None = None,
        distant: bool = False,
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
        player_id = state.player.resolved_character_id().lower()
        is_player = key == player_id or str(card.role or "").lower() == "player"
        lens_level = "named" if is_player else level(state, cid)
        role_map = roles or {}
        visible_role = role_map.get(key) or card.role
        cards.append(
            self.prompts.build_prompt_card(
                card,
                runtime_dict,
                render=render,
                lens_level=lens_level,
                visible_role=visible_role,
                distant=distant,
            )
        )
        card_ids.add(str(card.id).lower())
        card_ids.add(key)

    def _build_character_cards(
        self,
        state: GameState,
        active_arcs: list[str],
        *,
        render: bool = False,
    ) -> tuple[list[str], set[str]]:
        """Player sheet first (always), then present NPCs, then distant cast."""
        cards: list[str] = []
        card_ids: set[str] = set()
        roles = self.fronts.cast_role_map(state)
        player_id = state.player.resolved_character_id()
        self._append_character_card(
            character_id=player_id,
            state=state,
            active_arcs=active_arcs,
            cards=cards,
            card_ids=card_ids,
            render=render,
            roles=roles,
        )
        for character_id in state.characters_active:
            self._append_character_card(
                character_id=character_id,
                state=state,
                active_arcs=active_arcs,
                cards=cards,
                card_ids=card_ids,
                render=render,
                roles=roles,
            )
        for entry in self.fronts.distant_cast_entries(state):
            if len(cards) >= settings.wiki_page_cap:
                break
            self._append_character_card(
                character_id=entry.get("id") or "",
                state=state,
                active_arcs=active_arcs,
                cards=cards,
                card_ids=card_ids,
                render=render,
                roles=roles,
                distant=True,
            )
        return cards, card_ids

    def location_scene_extra(self, state: GameState) -> dict:
        """Hard scene facts from location runtime + access for canon_facts.extra.

        Atmosphere and ambient inherit from hyphen parent places when the
        current location runtime lacks them (child overrides parent).
        Events stay local — not inherited.
        """
        extra = dict(state.extra or {})
        loc_id = state.player.location
        if not loc_id:
            extra["player_known"] = known_ids(state, min_level="named")
            return extra
        runtime = state.locations.get(loc_id)
        atmosphere = runtime.atmosphere if runtime and runtime.atmosphere else None
        ambient = list(runtime.ambient) if runtime and runtime.ambient else []
        if runtime is not None and runtime.events:
            extra["location_events"] = list(runtime.events)
        if not atmosphere or not ambient:
            for ancestor in place_ancestors(loc_id):
                parent_rt = state.locations.get(ancestor)
                if parent_rt is None:
                    continue
                if not atmosphere and parent_rt.atmosphere:
                    atmosphere = parent_rt.atmosphere
                if not ambient and parent_rt.ambient:
                    ambient = list(parent_rt.ambient)
                if atmosphere and ambient:
                    break
        if atmosphere:
            extra["location_atmosphere"] = atmosphere
        if ambient:
            extra["location_ambient"] = ambient
        meta = {}
        try:
            meta = self.wiki.read_location_meta(loc_id) or {}
        except Exception:
            meta = {}
        kind = str(meta.get("kind") or "").strip().lower()
        danger = str(meta.get("danger") or "").strip().lower()
        access = str(meta.get("access") or "").strip().lower()
        if not kind or not danger:
            inferred_kind, inferred_danger = infer_location_kind(loc_id)
            kind = kind or inferred_kind
            danger = danger or inferred_danger
        if kind:
            extra["location_kind"] = kind
        if danger:
            extra["location_danger"] = danger
        if not access and kind in {"fortress", "outpost"}:
            access = "military"
        if access:
            extra["location_access"] = access
        extra["player_known"] = known_ids(state, min_level="named")
        distant = self.fronts.distant_cast_entries(state)
        if distant:
            extra["distant_cast"] = distant
        live = self.fronts.front_live_payload(state)
        if live:
            extra["front_live"] = live
            # Compat: Pass 1 prompts that still mention front_due_now
            if live.get("status") in {"live", "due"}:
                extra["front_due_now"] = {
                    "id": live["id"],
                    "title": live["title"],
                    "place": live["place"],
                    "bullets": list(live["bullets"]),
                }
        return extra

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
        roles = self.fronts.cast_role_map(state)

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
        pack = load_episode_pack(state.story_id)

        request = NarrativeRequest(
            canon_facts=NarrativeCanonFacts(
                location=state.player.location,
                time=tempo,
                present=list(state.characters_active),
                offscreen=format_offscreen_lines(state, roles=roles),
                situations=list(state.situations),
                player_findings=list(state.player_findings),
                known_ids=build_known_ids(state),
                extra=self.location_scene_extra(state),
            ),
            active_arc=arc_slice,
            story_so_far=self.story.build_story_slice(state),
            world_pages=world_pages,
            character_cards=cards,
            spellbook=spellbook,
            chat_recent=chat_recent,
            player_action=user_message,
            stance=stance,
            story_context=build_story_context(state.story_id),
            story_rules=load_story_episode_prompt(state.story_id),
            notoriety_slice=notoriety_prompt_slice(state, pack),
            scale_bands=list(pack.scale_bands.keys()),
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
        cards, _ = self._build_character_cards(state, active_arcs, render=True)
        return cards

    def _build_spellbook(
        self, raw_spells: list[dict[str, str]], user_message: str
    ) -> list[NarrativeSpellEntry]:
        def _entry(s: dict[str, str], *, include_desc: bool) -> NarrativeSpellEntry:
            return NarrativeSpellEntry(
                name=s["name"],
                description=(s.get("description") or "") if include_desc else "",
                output=s.get("output") or "effect",
                manifest=s.get("manifest") or "visible",
            )

        full = [_entry(s, include_desc=True) for s in raw_spells]
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
        return [_entry(s, include_desc=False) for s in raw_spells]

    def _compress_chat(self, recent: list[ChatMessage]) -> list[NarrativeChatTurn]:
        from app.narrative.action_tags import ensure_tags

        old_cap = settings.narrative_chat_old_char_cap
        turns: list[NarrativeChatTurn] = []
        n = len(recent)
        keep_full_from = max(0, n // 2) if old_cap > 0 else 0
        for i, m in enumerate(recent):
            content = m.content
            if old_cap > 0 and i < keep_full_from and len(content) > old_cap:
                content = content[:old_cap].rstrip() + "…"
            stored = list(m.tags or [])
            if m.role == "user":
                tags = list(ensure_tags(m.content, stored))
            else:
                tags = list(stored)
            turns.append(
                NarrativeChatTurn(
                    role=m.role,
                    content=content,
                    location=m.location,
                    present=list(m.present or []),
                    tags=tags,
                )
            )
        # Legacy assistant rows: inherit tags/present/location from preceding user beat.
        for i, turn in enumerate(turns):
            if turn.role != "assistant" or turn.tags:
                continue
            if i > 0 and turns[i - 1].role == "user":
                prev = turns[i - 1]
                turn.tags = list(prev.tags)
                if not turn.present and prev.present:
                    turn.present = list(prev.present)
                if not turn.location and prev.location:
                    turn.location = prev.location
        return turns
