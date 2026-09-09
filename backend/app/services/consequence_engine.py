import json

from app.config import settings
from app.models import (
    ConsolidationReviewResult,
    GameState,
    PresentReviewResult,
)
from app.services.front_engine import FrontEngine
from app.services.llm_client import LLMClient
from app.services.save_manager import SaveManager
from app.services.state_reducer import apply_scene_delta, present_review_to_delta
from app.services.token_estimate import estimate_prompt_tokens
from app.services.wiki_lint import WikiLint
from app.services.wiki_writer import WikiWriter


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
            "situations": list(state.situations),
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
        return (
            f"GAME STATE ATTUALE:\n{self._format_game_state(state)}\n\n"
            f"CONVERSAZIONE RECENTE:\n{transcript}\n\n"
            "Restituisci JSON conforme a PresentReviewResult.\n"
            f"player_location: aggiorna SE il luogo fisico e' cambiato {locations_hint}.\n"
            "characters_active: OBBLIGATORIO SEMPRE — lista COMPLETA sostitutiva "
            "di chi e' FISICAMENTE presente ORA (solo NPC; MAI il PG/id/nome/player); "
            "[] se solo; mai omettere.\n"
            "situations = memoria a MEDIO termine: fatti ancora veri e rilevanti "
            "per le prossime scene (viaggio in corso, voci/minacce aperte, accordi, "
            "tensioni locali, stato albo/missioni/registri: chi iscritto, posti liberi).\n"
            "Includi una situation SOLO SE: nelle prossime 2-3 scene un NPC, documento "
            "o evento potrebbe fare riferimento a questo fatto, e se mancasse la scena "
            "risulterebbe incoerente (es. un NPC che 'dimentica' di essere gia' arruolato).\n"
            "ESEMPI DA INCLUDERE: '[NPC] si e' unito al gruppo diretto a [luogo], "
            "partenza tra [tempo]' / 'Il player ha promesso a [NPC] di procurargli [oggetto]' / "
            "'[N] posti liberi nel registro di [organizzazione]'.\n"
            "ESEMPI DA NON INCLUDERE: saluti, micro-gesti, fatti statici di lore non "
            "legati a uno sviluppo di trama.\n"
            "Mantieni le situations attive tra 5 e 12; se superi, consolida o rimuovi "
            "prima di aggiungere.\n"
            "situations_add: aggiungi fili aperti utili incluso stato missioni; "
            "situations_remove: togli solo risolti/stale/rumore — NON togliere "
            "iscrizioni/registri aperti solo perche' dettagliati.\n"
            "front_impacts: solo strato 2 (null|distort|block + intent_id) se serve.\n"
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
        situations_block = "\n".join(f"- {s}" for s in state.situations) or "(nessuna)"
        return (
            f"PLAYER_ID (chiave obbligatoria in character_updates): {player_id}\n"
            f"PLAYER_NAME: {state.player.name}\n"
            f"PLAYER_LOCATION_WIKI: {sheet.get('location') or state.player.location}\n"
            f"PLAYER_LOCATION_STATE: {state.player.location}\n\n"
            f"SITUATIONS ATTUALI (candidati a promozione o state_cleanup):\n{situations_block}\n\n"
            f"OPEN THREADS ATTUALI (usa queste stringhe esatte in open_threads_remove):\n{threads_block}\n\n"
            f"MEMORIE ATTUALI (usa queste stringhe esatte in memories_remove; non riduplicarle):\n{memories_block}\n\n"
            f"GAME STATE ATTUALE:\n{self._format_game_state(state)}\n\n"
            f"CONVERSAZIONE RECENTE:\n{transcript}\n\n"
            "Sei nel passaggio da memoria a MEDIO termine (situations, volatile) a memoria "
            "a LUNGO termine (wiki, permanente). Ogni situation attuale ha tre destini "
            "possibili: (a) promossa in wiki se ha ancora valore permanente, (b) scartata "
            "con state_cleanup se risolta/assorbita, (c) lasciata in situations se ancora "
            "aperta e non abbastanza matura per la promozione.\n\n"
            f"DEVI aggiornare character_updates['{player_id}'] con:\n"
            "- memories_add: SOLO se tra 10+ scene questo fatto potrebbe ancora servire a "
            "definire chi e' il personaggio o cosa gli e' successo (background permanente, "
            "non cronaca). Test: 'se sparisse, il personaggio perderebbe un pezzo della sua "
            "storia?'. Se la risposta e' no, non e' una memoria.\n"
            "  INCLUDI: '[Il player] ha ottenuto [titolo/oggetto/status permanente] da [fonte]' "
            "/ '[Il player] ha causato/subito [evento con conseguenze durature]'.\n"
            "  NON INCLUDERE: log di azioni (cast, attacchi, spostamenti), riflessioni "
            "momentanee, micro-eventi senza conseguenze. Massimo poche voci dense per "
            "consolidamento — se stai aggiungendo piu' di 2-3 memorie, probabilmente stai "
            "loggando invece di ricordando.\n"
            "- memories_remove: per voci granulari o duplicate rispetto a quelle nuove.\n"
            "- spells_add: nuove abilita' apprese (finisce nello spellbook del player, non "
            "nella scheda).\n"
            "- open_threads_add/remove: se situations o la chat mostrano missioni, "
            "appuntamenti, accordi o compagni NON chiusi, DEVI metterli in "
            "open_threads_add (agenda del PG in wiki). Non lasciare Open threads "
            "vuoti in quel caso. Chiudi con open_threads_remove solo fili risolti "
            "(stringhe esatte sopra).\n"
            "- location: aggiorna se il player si e' spostato stabilmente.\n"
            "- memories_add: NON inventare titoli/status non assegnati in chat "
            "(iscriversi a una missione != ottenere un titolo).\n\n"
            "Se una situation risolta ha lasciato segni su luoghi, fazioni o comunita' "
            "(non sul singolo player), promuovila in location_updates o world_updates "
            "(events_add, tensions_add, sections_add) invece che nelle memorie del player. "
            "sections_add puo' creare sezioni wiki nuove se serve un contenitore che non "
            "esiste ancora.\n\n"
            "NON scrivere nella chat.\n\n"
            "state_cleanup: stringhe ESATTE da SITUATIONS ATTUALI da rimuovere dal game_state "
            "dopo la promozione (risolte, assorbite in wiki, o diventate rumore); [] se "
            "nessuna. Una situation non promossa e non risolta resta in situations — non "
            "va in state_cleanup solo perche' e' vecchia.\n\n"
            "Restituisci JSON ConsolidationReviewResult."
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
        self.apply_present_review(state, result)
        self.saves.save_game_state(state)
        return result

    def apply_present_review(self, state: GameState, result: PresentReviewResult) -> None:
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
        delta = present_review_to_delta(result, apply_presence=True)
        apply_scene_delta(state, delta)
        if delta.front_impacts:
            self.fronts.apply_impacts(state, delta.front_impacts)

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
            if item in state.situations:
                state.situations.remove(item)
        state.turns_since_consolidation = 0
        self.lint.run()
        self.saves.save_game_state(state)
        return result
