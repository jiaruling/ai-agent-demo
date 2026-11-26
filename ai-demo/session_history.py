import json
import os
import tempfile
from _thread import LockType
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Generator

# 判断是否运行在 Windows
if os.name == "nt":
    import msvcrt
else:
# 运行在其他操作系统上
    import fcntl

# 自定义错误，会话不存在
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

    # 在读写会话文件期间加锁，避免多个线程或进程同时操作
    # 生成器函数转换成上下文管理器，使它可以这样使用： with self._locked_file():
    @contextmanager
    def _locked_file(self) -> Generator[None, None, None]: # Generator[None, None, None] 是类型注解，分别表示 yield 的值、接收的值和最终返回值都是 None
        # 获取线程锁，防止当前 SessionHistory 实例，多个线程同时进入。离开 with 时自动释放
        with self._file_lock:
            # 打开锁文件，返回文件描述符 fd。os.O_CREAT：不存在就创建。os.O_RDWR：以读写方式打开。|：组合两个选项。0o600：八进制权限值
            fd = os.open(self._file_lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            # 把文件描述符包装成文件对象。"r+b" 表示二进制读写；离开 with 时自动关闭文件
            with os.fdopen(fd, "r+b") as file:
                # 判断是否运行在 Windows
                if os.name == "nt":
                    # 读取一个字节；如果锁文件为空，就写入一个空字节并立即刷新，供后面锁定
                    if not file.read(1):
                        file.write(b"\0")
                        file.flush()
                    # 将文件指针移到开头，获取锁文件第一个字节的锁
                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1) # file.fileno() 获取文件描述符；1 表示锁定一个字节
                else:
                    # 在非 Windows 系统上使用 flock 获取排他锁
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX)
                try:
                    yield # 执行到 yield 时暂停函数，让外层 with self._locked_file(): 里的代码运行
                finally: # 无论外层代码正常结束还是发生异常，都会执行这里的解锁操作
                    # 分别在 Windows 和非 Windows 系统上释放文件锁
                    if os.name == "nt":
                        file.seek(0)
                        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    # 获取所有会话数据，并检查数据格式是否合法，数据合法就返回
    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return {}
        # 格式检查
        if not isinstance(data, dict):
            raise ValueError(f"会话历史文件格式无效：{self.path}")
        # 更加详细的格式检查
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

    # 获取指定的会话，并返回其内容
    @staticmethod
    def _require_owner(
        sessions: dict[str, dict[str, Any]], session_id: str, owner_id: str
    ) -> dict[str, Any]:
        session = sessions.get(session_id)
        if session is None or session["owner_id"] != owner_id:
            raise SessionNotFound(session_id)
        return session

    #  添加用户消息
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

    # 添加ai助手消息
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
            # 只返回列表信息
            result = [
                {"id": session_id, "title": session["title"], "updated_at": session["updated_at"]}
                for session_id, session in sessions.items()
                if session["owner_id"] == owner_id
            ]
            # 根据时间倒序排
            return sorted(result, key=lambda session: session["updated_at"], reverse=True)

    def get_messages(self, session_id: str, owner_id: str) -> list[dict[str, Any]]:
        with self._locked_file():
            sessions = self._read()
            return self._require_owner(sessions, session_id, owner_id)["messages"]
