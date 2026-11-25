import json
import os
import tempfile
from _thread import LockType
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Generator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class SessionNotFound(Exception):
    pass


class SessionHistory:
    def __init__(self, path: Path):
        self.path = path
        self._file_lock_path = path.with_suffix(path.suffix + ".lock")
        self._file_lock = Lock()
        self._locks: dict[str, LockType] = {}
        self._locks_lock = Lock()

    def session_lock(self, session_id: str) -> LockType:
        with self._locks_lock:
            return self._locks.setdefault(session_id, Lock())

    @contextmanager
    def _locked_file(self) -> Generator[None, None, None]:
        with self._file_lock:
            fd = os.open(self._file_lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            with os.fdopen(fd, "r+b") as file:
                if os.name == "nt":
                    if not file.read(1):
                        file.write(b"\0")
                        file.flush()
                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if os.name == "nt":
                        file.seek(0)
                        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"会话历史文件格式无效：{self.path}")
        for session_id, session in data.items():
            if (
                not isinstance(session_id, str)
                or not isinstance(session, dict)
                or not all(isinstance(session.get(key), str) for key in ("owner_id", "title", "updated_at"))
                or not isinstance(session.get("messages"), list)
                or any(
                    not isinstance(message, dict)
                    or message.get("role") not in ("user", "assistant")
                    or not isinstance(message.get("content"), str)
                    or ("navigation" in message and not isinstance(message["navigation"], dict))
                    for message in session["messages"]
                )
            ):
                raise ValueError(f"会话历史文件格式无效：{self.path}")
        return data

    def _write(self, sessions: dict[str, dict[str, Any]]) -> None:
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".env.agent-history-", delete=False,
            ) as file:
                temp_path = Path(file.name)
                json.dump(sessions, file, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _require_owner(
        sessions: dict[str, dict[str, Any]], session_id: str, owner_id: str
    ) -> dict[str, Any]:
        session = sessions.get(session_id)
        if session is None or session["owner_id"] != owner_id:
            raise SessionNotFound(session_id)
        return session

    def add_user_message(self, session_id: str, owner_id: str, content: str) -> list[dict[str, Any]]:
        with self._locked_file():
            sessions = self._read()
            now = datetime.now(timezone.utc).isoformat()
            if session_id not in sessions:
                sessions[session_id] = {
                    "owner_id": owner_id,
                    "title": content.strip()[:40] or "新会话",
                    "updated_at": now,
                    "messages": [],
                }
            session = self._require_owner(sessions, session_id, owner_id)
            session["messages"].append({"role": "user", "content": content})
            session["updated_at"] = now
            self._write(sessions)
            return session["messages"]

    def add_assistant_message(
        self, session_id: str, owner_id: str, content: str, navigation: dict | None
    ) -> None:
        with self._locked_file():
            sessions = self._read()
            session = self._require_owner(sessions, session_id, owner_id)
            message: dict[str, Any] = {"role": "assistant", "content": content}
            if navigation:
                message["navigation"] = navigation
            session["messages"].append(message)
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write(sessions)

    def list_sessions(self, owner_id: str) -> list[dict[str, Any]]:
        with self._locked_file():
            sessions = self._read()
            result = [
                {"id": session_id, "title": session["title"], "updated_at": session["updated_at"]}
                for session_id, session in sessions.items()
                if session["owner_id"] == owner_id
            ]
            return sorted(result, key=lambda session: session["updated_at"], reverse=True)

    def get_messages(self, session_id: str, owner_id: str) -> list[dict[str, Any]]:
        with self._locked_file():
            sessions = self._read()
            return self._require_owner(sessions, session_id, owner_id)["messages"]
