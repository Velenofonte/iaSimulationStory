import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.config import settings
from app.models import ChatMessage, GameState, PlayerState
from app.services.game_clock import ensure_clock_fields, sync_time_label
from app.services.story_catalog import load_story_meta, resolve_seed_wiki


class SaveManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.saves_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str, *, create: bool = False) -> Path:
        path = self.root / session_id
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def wiki_dir(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "wiki"

    def game_state_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "game_state.json"

    def chat_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "chat.jsonl"

    def undo_dir(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "undo"

    def _undo_stack_path(self, session_id: str) -> Path:
        return self.undo_dir(session_id) / "stack.json"

    def _undo_slot_dir(self, session_id: str, slot_id: str) -> Path:
        return self.undo_dir(session_id) / "slots" / slot_id

    def _read_undo_stack(self, session_id: str) -> list[str]:
        """Lista slot dal più vecchio al più recente. Migra formato legacy a 1 slot."""
        undo = self.undo_dir(session_id)
        stack_path = self._undo_stack_path(session_id)
        if stack_path.is_file():
            try:
                data = json.loads(stack_path.read_text(encoding="utf-8"))
                slots = data.get("slots") if isinstance(data, dict) else data
                if isinstance(slots, list):
                    return [str(s) for s in slots if str(s).strip()]
            except Exception:
                return []

        # Legacy: undo/game_state.json a livello root
        if (undo / "game_state.json").is_file():
            slot_id = "legacy"
            slot = self._undo_slot_dir(session_id, slot_id)
            if slot.exists():
                shutil.rmtree(slot)
            slot.mkdir(parents=True)
            for name in ("game_state.json", "chat.jsonl", "meta.json"):
                src = undo / name
                if src.is_file():
                    shutil.move(str(src), str(slot / name))
            legacy_wiki = undo / "wiki"
            if legacy_wiki.is_dir():
                shutil.move(str(legacy_wiki), str(slot / "wiki"))
            self._write_undo_stack(session_id, [slot_id])
            return [slot_id]
        return []

    def _write_undo_stack(self, session_id: str, slots: list[str]) -> None:
        undo = self.undo_dir(session_id)
        undo.mkdir(parents=True, exist_ok=True)
        self._undo_stack_path(session_id).write_text(
            json.dumps({"slots": slots}, indent=2),
            encoding="utf-8",
        )

    def undo_count(self, session_id: str) -> int:
        return len(self._read_undo_stack(session_id))

    def has_undo_checkpoint(self, session_id: str) -> bool:
        return self.undo_count(session_id) > 0

    def clear_undo_checkpoint(self, session_id: str) -> None:
        path = self.undo_dir(session_id)
        if path.exists():
            shutil.rmtree(path)

    def _snapshot_current_into(self, session_id: str, dest: Path) -> None:
        gs = self.game_state_path(session_id)
        if not gs.is_file():
            raise FileNotFoundError(f"Session not found: {session_id}")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        shutil.copy2(gs, dest / "game_state.json")
        chat = self.chat_path(session_id)
        if chat.is_file():
            shutil.copy2(chat, dest / "chat.jsonl")
        else:
            (dest / "chat.jsonl").touch()

        wiki = self.wiki_dir(session_id)
        dest_wiki = dest / "wiki"
        if wiki.is_dir():
            shutil.copytree(
                wiki,
                dest_wiki,
                ignore=shutil.ignore_patterns(".obsidian", "__pycache__", "*.pyc"),
            )
        else:
            dest_wiki.mkdir(parents=True)

        meta = {"created_at": datetime.now(timezone.utc).isoformat()}
        (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def _apply_snapshot_dir(self, session_id: str, slot: Path) -> None:
        undo_gs = slot / "game_state.json"
        if not undo_gs.is_file():
            raise FileNotFoundError(f"Corrupt undo slot: {slot}")

        shutil.copy2(undo_gs, self.game_state_path(session_id))

        undo_chat = slot / "chat.jsonl"
        chat_dest = self.chat_path(session_id)
        if undo_chat.is_file():
            shutil.copy2(undo_chat, chat_dest)
        else:
            chat_dest.write_text("", encoding="utf-8")

        wiki = self.wiki_dir(session_id)
        if wiki.exists():
            shutil.rmtree(wiki)
        undo_wiki = slot / "wiki"
        if undo_wiki.is_dir():
            shutil.copytree(
                undo_wiki,
                wiki,
                ignore=shutil.ignore_patterns(".obsidian", "__pycache__", "*.pyc"),
            )
        else:
            wiki.mkdir(parents=True)

    def write_undo_checkpoint(self, session_id: str) -> None:
        """Push snapshot pre-turno (max settings.undo_checkpoint_depth). Solo I/O."""
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("Invalid session id")
        if not self.game_state_path(sid).is_file():
            raise FileNotFoundError(f"Session not found: {sid}")

        depth = max(1, int(settings.undo_checkpoint_depth or 1))
        stack = self._read_undo_stack(sid)
        slot_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        # Evita collisioni nello stesso microsecondo
        while slot_id in stack or self._undo_slot_dir(sid, slot_id).exists():
            slot_id = f"{slot_id}_{uuid.uuid4().hex[:6]}"

        self._snapshot_current_into(sid, self._undo_slot_dir(sid, slot_id))
        stack.append(slot_id)

        while len(stack) > depth:
            old = stack.pop(0)
            old_dir = self._undo_slot_dir(sid, old)
            if old_dir.exists():
                shutil.rmtree(old_dir)

        self._write_undo_stack(sid, stack)

    def restore_undo_checkpoint(self, session_id: str) -> GameState:
        """Pop dello snapshot più recente e restore. Solo I/O — nessun LLM."""
        sid = (session_id or "").strip()
        stack = self._read_undo_stack(sid)
        if not stack:
            raise FileNotFoundError(f"No undo checkpoint for session: {sid}")

        slot_id = stack.pop()
        slot = self._undo_slot_dir(sid, slot_id)
        if not (slot / "game_state.json").is_file():
            self._write_undo_stack(sid, stack)
            if slot.exists():
                shutil.rmtree(slot)
            raise FileNotFoundError(f"No undo checkpoint for session: {sid}")

        self._apply_snapshot_dir(sid, slot)
        shutil.rmtree(slot)
        if stack:
            self._write_undo_stack(sid, stack)
        else:
            self.clear_undo_checkpoint(sid)
        return self.load_game_state(sid)

    def active_path(self) -> Path:
        return self.root / "active.json"

    def set_active_session(self, session_id: str) -> None:
        path = self.active_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"session_id": session_id}, indent=2),
            encoding="utf-8",
        )

    def get_active_session_id(self) -> str | None:
        path = self.active_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sid = str(data.get("session_id") or "").strip()
            if sid and self.game_state_path(sid).exists():
                return sid
        except Exception:
            return None
        return None

    def create_session(
        self,
        player_name: str = "Avventuriero",
        start_location: str | None = None,
        *,
        story_id: str | None = None,
        character_id: str | None = None,
        origin: str = "custom",
        race: str | None = None,
    ) -> GameState:
        story_id = (story_id or settings.default_story_id).strip()
        meta = load_story_meta(story_id)
        location = (start_location or str(meta.get("start_location") or "e-rantel")).strip()
        seed = resolve_seed_wiki(story_id)

        session_id = str(uuid.uuid4())
        self.session_dir(session_id, create=True)
        dest_wiki = self.wiki_dir(session_id)
        if dest_wiki.exists():
            shutil.rmtree(dest_wiki)
        shutil.copytree(
            seed,
            dest_wiki,
            ignore=shutil.ignore_patterns(".obsidian", "__pycache__", "*.pyc"),
        )

        cid = (character_id or "").strip() or player_name.lower().replace(" ", "-")
        player_origin: Literal["lore", "custom"] = "lore" if origin == "lore" else "custom"
        state = GameState(
            session_id=session_id,
            story_id=story_id,
            player=PlayerState(
                name=player_name,
                location=location,
                character_id=cid,
                origin=player_origin,
                race=race,
            ),
        )
        sync_time_label(state)
        self.save_game_state(state)
        self.chat_path(session_id).touch()
        story_name = str(meta.get("name") or story_id)
        location_label = "-".join(
            part[:1].upper() + part[1:] if part else part
            for part in location.replace("_", "-").split("-")
        )
        welcome = (
            f"Sei a {location_label}, nel mondo di {story_name}. "
            "Mercanti, avventurieri e voci di mostri riempiono le strade."
        )
        self.append_chat(
            session_id,
            ChatMessage(role="assistant", content=welcome, location=location),
        )
        self.set_active_session(session_id)
        return state

    def list_sessions(self) -> list[dict]:
        items: list[dict] = []
        active_id = self.get_active_session_id()
        if not self.root.exists():
            return items
        for path in self.root.iterdir():
            gs = path / "game_state.json"
            if not path.is_dir() or not gs.exists():
                continue
            try:
                state = GameState.model_validate(json.loads(gs.read_text(encoding="utf-8")))
                if ensure_clock_fields(state):
                    self.save_game_state(state)
            except Exception:
                continue
            chat = path / "chat.jsonl"
            mtime = gs.stat().st_mtime
            if chat.exists():
                mtime = max(mtime, chat.stat().st_mtime)
            story_name = state.story_id
            try:
                story_name = str(load_story_meta(state.story_id).get("name") or state.story_id)
            except Exception:
                pass
            items.append(
                {
                    "session_id": state.session_id,
                    "story_id": state.story_id,
                    "story_name": story_name,
                    "player_name": state.player.name,
                    "location": state.player.location,
                    "time": state.time,
                    "updated_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                    "active": state.session_id == active_id,
                }
            )
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return items

    def delete_session(self, session_id: str) -> None:
        """Rimuove l'intera cartella sessione (game_state, chat, wiki clone) e active se punta lì."""
        sid = (session_id or "").strip()
        if not sid or sid in {".", ".."} or "/" in sid or "\\" in sid:
            raise ValueError(f"Invalid session id: {session_id!r}")
        path = (self.root / sid).resolve()
        root = self.root.resolve()
        if path == root or root not in path.parents:
            raise ValueError(f"Invalid session path: {session_id!r}")
        if not path.is_dir() or not (path / "game_state.json").exists():
            raise FileNotFoundError(f"Session not found: {session_id}")
        if self.get_active_session_id() == sid:
            active = self.active_path()
            if active.exists():
                active.unlink()
        # Intera sessione: game_state.json, chat.jsonl, wiki/, eventuali tmp
        shutil.rmtree(path)

    def load_game_state(self, session_id: str) -> GameState:
        path = self.game_state_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        state = GameState.model_validate(data)
        if ensure_clock_fields(state):
            self.save_game_state(state)
        return state

    def save_game_state(self, state: GameState) -> None:
        path = self.game_state_path(state.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def append_chat(self, session_id: str, message: ChatMessage) -> None:
        path = self.chat_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message.model_dump_json() + "\n")

    def load_recent_chat(self, session_id: str, limit: int | None = None) -> list[ChatMessage]:
        limit = limit or settings.recent_chat_messages
        path = self.chat_path(session_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        messages = [ChatMessage.model_validate_json(line) for line in lines if line.strip()]
        return messages[-limit:]

    def load_all_chat(self, session_id: str) -> list[ChatMessage]:
        path = self.chat_path(session_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [ChatMessage.model_validate_json(line) for line in lines if line.strip()]
