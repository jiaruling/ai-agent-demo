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
    import msvcrt # msvcrt 是 Windows 下的一个模块，提供了对 C 运行时库的访问，包括文件锁定功能
else:
# 运行在其他操作系统上
    import fcntl # fcntl 是 Unix 系统下的一个模块，提供了对文件描述符的操作，包括文件锁定功能

# 自定义错误，会话不存在
class SessionNotFound(Exception):
    pass


class SessionHistory:
    # 初始化函数，初始化时自动调用
    def __init__(self, path: Path):
        self.path = path  # 会话历史文件的路径
        self._file_lock_path = path.with_suffix(path.suffix + ".lock") # 锁文件的路径，和会话历史文件同目录，后缀为 .lock
        self._file_lock = Lock() # 线程锁，防止多个线程同时操作会话历史文件
        self._locks: dict[str, LockType] = {} # 存储每个会话的锁，避免多个线程同时操作同一个会话
        self._locks_lock = Lock() # 线程锁，防止多个线程同时操作 _locks 字典

    # 获取指定会话的锁，如果不存在就创建一个新的锁
    def session_lock(self, session_id: str) -> LockType:
        with self._locks_lock:
            return self._locks.setdefault(session_id, Lock()) # 如果字典中存在指定键，则返回该键对应的值；如果不存在，则创建一个新的键值对，并返回新创建的值

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
            # 读取会话历史文件，如果文件不存在就返回空字典
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file) # 将 JSON 格式的字符串转换成 Python 对象
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

    # 将会话数据写入文件
    def _write(self, sessions: dict[str, dict[str, Any]]) -> None:
        temp_path = None
        try:
            # 使用临时文件写入会话历史，避免写入过程中出现异常导致文件损坏
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".env.agent-history-", delete=False,
            ) as file:
                temp_path = Path(file.name)
                json.dump(sessions, file, ensure_ascii=False, indent=2)
            # 将临时文件替换为会话历史文件，原子操作，避免文件损坏
            os.replace(temp_path, self.path)
        finally:
            # 删除临时文件，如果它还存在的话
            if temp_path is not None and temp_path.exists():
                temp_path.unlink() # 删除文件

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
            # 如果会话不存在，就创建一个新的会话
            if session_id not in sessions:
                sessions[session_id] = {
                    "owner_id": owner_id,
                    "title": content.strip()[:40] or "新会话",
                    "updated_at": now,
                    "messages": [],
                }
            session = self._require_owner(sessions, session_id, owner_id)
            messages: dict[str, Any] = {"role": "user", "content": content}
            session["messages"].append(messages)
            session["updated_at"] = now
            self._write(sessions)
            return session["messages"] # 返回当前会话的所有消息列表

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

    # 获取指定用户的所有会话列表，并按更新时间倒序排列
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

    # 获取指定会话的所有消息
    def get_messages(self, session_id: str, owner_id: str) -> list[dict[str, Any]]:
        with self._locked_file():
            sessions = self._read()
            return self._require_owner(sessions, session_id, owner_id)["messages"]
