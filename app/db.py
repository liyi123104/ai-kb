"""SQLite 读写（计划书 6.1 / T2.6）：对话历史落库。

两张表：
    sessions(id TEXT PRIMARY KEY, created_at TEXT)
    messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,
             content TEXT, sources TEXT, created_at TEXT)

为什么用 SQLite：单用户、单文件、零运维，数据量小（计划书第 2 节选型）。
所有 SQL 都用参数绑定，不拼字符串。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Iterator

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    sources     TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """每次操作一个短连接；WAL 提升并发读能力。"""
    conn = sqlite3.connect(str(settings.db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)


def new_session_id() -> str:
    return uuid.uuid4().hex[:16]


def ensure_session(session_id: str, created_at: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO sessions(id, created_at) VALUES (?, ?)",
                     (session_id, created_at))


def add_message(session_id: str, role: str, content: str, created_at: str,
                sources: list[dict] | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages(session_id, role, content, sources, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content,
             json.dumps(sources, ensure_ascii=False) if sources else None, created_at),
        )


def save_turn(session_id: str, question: str, answer: str, sources: list[dict],
              created_at: str) -> str:
    """把一轮问答写成两条消息（user + assistant），返回实际使用的 session_id。"""
    sid = session_id or new_session_id()
    ensure_session(sid, created_at)
    add_message(sid, "user", question, created_at)
    add_message(sid, "assistant", answer, created_at, sources)
    return sid


def get_history(session_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content, sources, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "role": r["role"],
            "content": r["content"],
            "sources": json.loads(r["sources"]) if r["sources"] else [],
            "created_at": r["created_at"],
        })
    return out


def list_sessions(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT s.id, s.created_at, COUNT(m.id) AS messages "
            "FROM sessions s LEFT JOIN messages m ON m.session_id = s.id "
            "GROUP BY s.id ORDER BY s.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"session_id": r["id"], "created_at": r["created_at"],
             "messages": r["messages"]} for r in rows]
