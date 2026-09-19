import json

from app.config import settings
from app.models import (
    ChatMessage,
    ConsolidationReviewResult,
    GameState,
    PresentReviewResult,
)
from app.story.front_engine import FrontEngine
from app.llm.llm_client import LLMClient
from app.player.places import infer_location_kind, normalize_place_id
from app.persistence.save_manager import SaveManager
from app.turn.state_reducer import apply_scene_delta, present_review_to_delta
from app.narrative.token_estimate import estimate_prompt_tokens
from app.wiki.wiki_lint import WikiLint
from app.wiki.wiki_writer import WikiWriter


class ConsequenceEngine:
    def __init__(
        self,
        *,
        wiki_writer: WikiWriter | None = None,
        lint: WikiLint | None = None,
        fronts: FrontEngine | None = None,
        saves: SaveManager | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.saves = saves or SaveManager()
        self.wiki_writer = wiki_writer or WikiWriter()
        self.lint = lint or WikiLint(wiki_dir=self.wiki_writer.wiki_dir)
        self.fronts = fronts or FrontEngine(wiki=self.wiki_writer)
        self.last_review_tokens: int = 0

    def should_run_present_review(self, state: GameState) -> bool:
        return state.turns_since_present_review >= settings.present_review_every_n

    def should_run_consolidation_review(self, state: GameState) -> bool:
        return state.turns_since_consolidation >= settings.consolidate_every_n

    def _format_game_state(self, state: GameState) -> str:
        if settings.review_state_slice:
            return self._state_slice_json(state)
        return state.model_dump_json(indent=2)

    def _state_slice_json(self, state: GameState) -> str:
        """Compact review context: location, present, situations, moods, front cursors."""
        present_runtime: dict = {}
        for cid in state.characters_active:
            runtime = state.characters.get(cid)
            if runtime:
                present_runtime[cid] = {
                    "mood": runtime.mood,
                    "relationship": runtime.relationship,
                    "location": runtime.location,
                    "npc_knowledge": [
                        {"id": f.id, "summary": f.summary} for f in runtime.npc_knowledge
                    ],
                }
            else:
                present_runtime[cid] = {}
        fronts_slice: dict = {}
        for fid, fr in state.fronts.items():
            fronts_slice[fid] = {
                "status": fr.status,
                "cursor_beat": fr.cursor_beat,
                "last_fired_beat": fr.last_fired_beat,
            }
        payload = {
            "day": state.day,
            "minutes": state.minutes,
            "time": state.time,
            "player": {
                "name": state.player.name,
                "location": state.player.location,
            },
            "characters_active": list(state.characters_active),
            "characters_present": present_runtime,
            "characters_offscreen": {
                cid: {
                    "where": entry.where,
                    "reason": entry.reason,
                    "from_location": entry.from_location,
                }
                for cid, entry in state.characters_offscreen.items()
            },
            "situations": [
                {"id": s.id, "summary": s.summary} for s in state.situations
            ],
            "party_active": state.party_active,
            "fronts": fronts_slice,
            "extra": dict(state.extra),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _record_usage(self, system: str, user: str) -> None:
        usage = self.llm.last_usage
        if usage and usage.get("prompt_tokens"):
            self.last_review_tokens = int(usage["prompt_tokens"])
        else:
            self.last_review_tokens = estimate_prompt_tokens(system, user)

    def _valid_location_ids(self) -> list[str]:
        """Id location conosciuti dalla wiki corrente — nessun hardcoding di lore."""
        try:
            return self.wiki_writer.list_location_ids()
        except AttributeError:
            # fallback se WikiWriter non espone ancora questo metodo
            return list(getattr(settings, "known_location_ids", []) or [])

    def _build_present_user(self, state: GameState, transcript: str) -> str:
        locations = self._valid_location_ids()
        locations_hint = (
            f"(id validi: {', '.join(locations)})" if locations
            else "(usa l'id gia' presente in game_state se non cambia)"
        )
        situations_block = (
            "\n".join(f"- {s.id}: {s.summary}" for s in state.situations) or "(nessuna)"
        )
        knowledge_lines: list[str] = []
        for cid, runtime in state.characters.items():
            if not runtime or not runtime.npc_knowledge:
                continue
            facts = "; ".join(f"{f.id}: {f.summary}" for f in runtime.npc_knowledge)
            knowledge_lines.append(f"- {cid}: {facts}")
        knowledge_block = "\n".join(knowledge_lines) or "(nessuna)"
        return (
            f"GAME STATE ATTUALE:\n{self._format_game_state(state)}\n\n"
            f"SITUATIONS ATTUALI (id: summary):\n{situations_block}\n\n"
            f"NPC_KNOWLEDGE RUNTIME (known_ids):\n{knowledge_block}\n\n"
            f"CONVERSAZIONE RECENTE:\n{transcript}\n\n"
            f"LOCATION ID VALIDI: {locations_hint}\n\n"
            "Applica il system prompt. Restituisci JSON PresentReviewResult."
        )
    def _build_consolidation_user(
        self,
        state: GameState,
        *,
        player_id: str,
        sheet: dict,
        threads_block: str,
        memories_block: str,
        transcript: str,
    ) -> str:
        situations_block = (
            "\n".join(f"- {s.id}: {s.summary}" for s in state.situations) or "(nessuna)"
        )
        knowledge_lines: list[str] = []
        for cid in state.characters_active:
            runtime = state.characters.get(cid)
            if not runtime or not runtime.npc_knowledge:
                continue
            facts = "; ".join(f"{f.id}: {f.summary}" for f in runtime.npc_knowledge)
            knowledge_lines.append(f"- {cid}: {facts}")
        for cid, runtime in state.characters.items():
            if cid in state.characters_active:
                continue
            if not runtime.npc_knowledge:
                continue
            facts = "; ".join(f"{f.id}: {f.summary}" for f in runtime.npc_knowledge)
            knowledge_lines.append(f"- {cid}: {facts}")
        knowledge_block = "\n".join(knowledge_lines) or "(nessuna)"
        return (
            f"PLAYER_ID (chiave obbligatoria in character_updates): {player_id}\n"
            f"PLAYER_NAME: {state.player.name}\n"
            f"PLAYER_LOCATION_WIKI: {sheet.get('location') or state.player.location}\n"
            f"PLAYER_LOCATION_STATE: {state.player.location}\n\n"
            f"SITUATIONS ATTUALI (id: summary; candidati a promozione o state_cleanup):\n"
            f"{situations_block}\n\n"
            f"NPC_KNOWLEDGE RUNTIME (fatti per-NPC da comprimere in Relazione):\n"
            f"{knowledge_block}\n\n"
            f"OPEN THREADS ATTUALI (stringhe esatte per open_threads_remove):\n"
            f"{threads_block}\n\n"
            f"MEMORIE ATTUALI (stringhe esatte per memories_remove):\n"
            f"{memories_block}\n\n"
            f"GAME STATE ATTUALE:\n{self._format_game_state(state)}\n\n"
            f"CONVERSAZIONE RECENTE:\n{transcript}\n\n"
            "Applica il system prompt. Restituisci JSON ConsolidationReviewResult."
        )

    def run_present_review(self, state: GameState) -> PresentReviewResult | None:
        self.last_review_tokens = 0
        recent = self.saves.load_recent_chat(
            state.session_id, limit=settings.review_chat_messages
        )
        transcript = "\n".join(f"{m.role}: {m.content}" for m in recent)
        system = self.llm.load_prompt("review_present")
        user = self._build_present_user(state, transcript)
        try:
            result = self.llm.complete_json(
                system=system,
                user=user,
                schema=PresentReviewResult,
                model=settings.llm_model_review,
            )
        except Exception as exc:
            print(f"[present_review] failed: {exc}")
            return None
        self._record_usage(system, user)
        self.apply_present_review(state, result, recent=recent)
        self.saves.save_game_state(state)
        return result

    @staticmethod
    def clamp_present_review_to_chat(
        result: PresentReviewResult,
        recent: list[ChatMessage],
    ) -> None:
        """Review may drop cast members; it must not re-admit ids past the last chat present."""
        ceiling: list[str] | None = None
        for msg in reversed(recent or []):
            if (msg.role or "").strip().lower() != "assistant":
                continue
            ceiling = list(msg.present or [])
            break
        if ceiling is None:
            return
        allowed = {
            str(x).strip().casefold()
            for x in ceiling
            if str(x or "").strip()
        }
        result.characters_active = [
            cid
            for cid in list(result.characters_active or [])
            if str(cid).strip().casefold() in allowed
        ]

    def apply_present_review(
        self,
        state: GameState,
        result: PresentReviewResult,
        *,
        recent: list[ChatMessage] | None = None,
    ) -> None:
        if recent is not None:
            self.clamp_present_review_to_chat(result, recent)
        orphan = result.location_updates.pop("_scene", None)
        if orphan is not None:
            loc_id = (result.player_location or state.player.location or "").strip()
            if loc_id:
                existing = result.location_updates.get(loc_id)
                if existing is None:
                    result.location_updates[loc_id] = orphan
                else:
                    if orphan.atmosphere and not existing.atmosphere:
                        existing.atmosphere = orphan.atmosphere
                    if orphan.objects:
                        existing.objects = list(dict.fromkeys([*existing.objects, *orphan.objects]))
                    if orphan.events:
                        existing.events = list(dict.fromkeys([*existing.events, *orphan.events]))
        # Ensure stubs for new location ids so the episode engine can read kind/danger.
        known = set(self._valid_location_ids())
        candidates = []
        if result.player_location:
            candidates.append(result.player_location)
        candidates.extend(result.location_updates.keys())
        for raw_id in candidates:
            lid = str(raw_id or "").strip()
            if not lid or lid.startswith("_"):
                continue
            norm = normalize_place_id(lid) or lid.lower().replace("_", "-")
            if lid in known or norm in known:
                continue
            kind, danger = infer_location_kind(norm)
            try:
                self.wiki_writer.ensure_location(norm, kind=kind, danger=danger)
                known.add(norm)
            except Exception as exc:
                print(f"[present_review] ensure_location failed for {norm}: {exc}")

        delta = present_review_to_delta(result, apply_presence=True, state=state)
        apply_scene_delta(state, delta)
        if delta.front_impacts:
            self.fronts.apply_impacts(state, delta.front_impacts)
        if result.beat_commit is not None:
            path = (result.beat_commit.path or "still_live").strip().lower()
            if path in {"canon", "alt"}:
                note = result.beat_commit.note
                outcome = self.fronts.commit_live_beat(
                    state, path=path, note=note, hydrate_scene=True
                )
                from app.turn.state_reducer import apply_front_outcome

                apply_front_outcome(state, outcome)

    def run_consolidation_review(self, state: GameState) -> ConsolidationReviewResult | None:
        self.last_review_tokens = 0
        recent = self.saves.load_recent_chat(
            state.session_id, limit=settings.consolidate_chat_messages
        )
        transcript = "\n".join(f"{m.role}: {m.content}" for m in recent)
        player_id = state.player.resolved_character_id()
        self.wiki_writer.ensure_player(
            state.player.name,
            state.player.location,
            character_id=player_id,
        )
        sheet = self.wiki_writer.read_character(player_id)
        open_threads = self.wiki_writer.get_section(sheet["body"], "Open threads")
        memories = self.wiki_writer.get_section(sheet["body"], "Memorie")
        threads_block = "\n".join(f"- {t}" for t in open_threads) or "(nessuno)"
        memories_block = "\n".join(f"- {m}" for m in memories) or "(nessuna)"
        system = self.llm.load_prompt("review_consolidate")
        user = self._build_consolidation_user(
            state,
            player_id=player_id,
            sheet=sheet,
            threads_block=threads_block,
            memories_block=memories_block,
            transcript=transcript,
        )
        try:
            result = self.llm.complete_json(
                system=system,
                user=user,
                schema=ConsolidationReviewResult,
                model=settings.llm_model_review,
            )
        except Exception as exc:
            print(f"[consolidation_review] failed: {exc}")
            return None

        self._record_usage(system, user)

        normalized: dict = {}
        for key, update in result.character_updates.items():
            kid = key.strip().lower().replace(" ", "-")
            if kid in {"player", state.player.name.lower().replace(" ", "-"), player_id}:
                normalized[player_id] = update
            else:
                normalized[kid] = update
        result.character_updates = normalized

        self.wiki_writer.apply_consolidation(result)
        if result.party_active:
            state.party_active = result.party_active
        for item in result.state_cleanup:
            rid = str(item or "").strip()
            if not rid:
                continue
            state.situations = [
                s
                for s in state.situations
                if s.id != rid
                and s.id.casefold() != rid.casefold()
                and s.summary != rid
                and s.summary.casefold() != rid.casefold()
            ]
        # Deterministic promote of notoriety runtime → wiki section (setting-agnostic).
        try:
            from app.episodes.notoriety import format_wiki_section

            lines = format_wiki_section(state)
            if lines:
                self.wiki_writer.write_notoriety_section(player_id, lines)
        except Exception as exc:
            print(f"[consolidation] notoriety wiki write failed: {exc}")
        state.turns_since_consolidation = 0
        self.lint.run()
        self.saves.save_game_state(state)
        return result
