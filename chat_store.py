import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

CHAT_STORE = os.getenv("CHAT_STORE", "sqlite").strip().lower()  # sqlite | none (future: dynamodb)
CHAT_DB_PATH = os.getenv("CHAT_DB_PATH", "./chat_store.db")

def _now_ts() -> int:
    return int(time.time())

@dataclass
class ChatSession:
    tenant_id: str
    user_email: str
    session_id: str
    title: str
    created_at: int
    updated_at: int

class ChatStore:
    def __init__(self, store: Optional[str] = None, db_path: Optional[str] = None):
        self.store = (store or CHAT_STORE).strip().lower()
        self.db_path = db_path or CHAT_DB_PATH

        if self.store not in ("sqlite", "none"):
            # Keep it strict: if misconfigured, disable.
            self.store = "none"

        if self.store == "sqlite":
            self._init_sqlite()

    def enabled(self) -> bool:
        return self.store != "none"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    tenant_id TEXT NOT NULL,
                    user_email TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    title TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (tenant_id, user_email, session_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    tenant_id TEXT NOT NULL,
                    user_email TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT,
                    sources_json TEXT,
                    PRIMARY KEY (tenant_id, user_email, session_id, ts, role)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
                ON chat_sessions (tenant_id, user_email, updated_at DESC)
                """
            )
            conn.commit()

    def create_session(self, tenant_id: str, user_email: str, title: Optional[str] = None) -> str:
        if not self.enabled():
            return str(uuid.uuid4())

        tenant_id = tenant_id or "viva"
        user_email = (user_email or "").strip().lower()
        session_id = str(uuid.uuid4())
        now = _now_ts()
        safe_title = (title or "Nueva conversación").strip()[:120]

        if self.store == "sqlite":
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO chat_sessions (tenant_id, user_email, session_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (tenant_id, user_email, session_id, safe_title, now, now),
                )
                conn.commit()

        return session_id

    def touch_session(self, tenant_id: str, user_email: str, session_id: str, title: Optional[str] = None) -> None:
        if not self.enabled():
            return

        tenant_id = tenant_id or "viva"
        user_email = (user_email or "").strip().lower()
        now = _now_ts()

        if self.store == "sqlite":
            with self._connect() as conn:
                if title is None:
                    conn.execute(
                        """
                        UPDATE chat_sessions
                        SET updated_at = ?
                        WHERE tenant_id = ? AND user_email = ? AND session_id = ?
                        """,
                        (now, tenant_id, user_email, session_id),
                    )
                else:
                    safe_title = (title or "").strip()[:120]
                    conn.execute(
                        """
                        UPDATE chat_sessions
                        SET updated_at = ?, title = COALESCE(NULLIF(title,''), ?)
                        WHERE tenant_id = ? AND user_email = ? AND session_id = ?
                        """,
                        (now, safe_title, tenant_id, user_email, session_id),
                    )
                conn.commit()

    def add_message(
        self,
        tenant_id: str,
        user_email: str,
        session_id: str,
        role: str,
        content: str,
        model: Optional[str] = None,
        sources: Optional[List[str]] = None,
        ts: Optional[int] = None,
    ) -> int:
        if not self.enabled():
            return _now_ts()

        tenant_id = tenant_id or "viva"
        user_email = (user_email or "").strip().lower()
        ts = int(ts or _now_ts())
        role = role or "user"
        content = content or ""

        # Title is created from first user message (if it exists and if title is default)
        if role == "user":
            title = content.strip().replace("\n", " ")
            if title:
                self.touch_session(tenant_id, user_email, session_id, title=title[:80])

        if self.store == "sqlite":
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO chat_messages
                    (tenant_id, user_email, session_id, ts, role, content, model, sources_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        user_email,
                        session_id,
                        ts,
                        role,
                        content,
                        model,
                        json.dumps(sources or []),
                    ),
                )
                conn.execute(
                    """
                    UPDATE chat_sessions
                    SET updated_at = ?
                    WHERE tenant_id = ? AND user_email = ? AND session_id = ?
                    """,
                    (ts, tenant_id, user_email, session_id),
                )
                conn.commit()
        return ts

    def list_sessions(self, tenant_id: str, user_email: str, limit: int = 30) -> List[ChatSession]:
        if not self.enabled():
            return []

        tenant_id = tenant_id or "viva"
        user_email = (user_email or "").strip().lower()

        if self.store == "sqlite":
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT tenant_id, user_email, session_id, title, created_at, updated_at
                    FROM chat_sessions
                    WHERE tenant_id = ? AND user_email = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (tenant_id, user_email, int(limit)),
                ).fetchall()

            return [
                ChatSession(
                    tenant_id=r["tenant_id"],
                    user_email=r["user_email"],
                    session_id=r["session_id"],
                    title=r["title"] or "Conversación",
                    created_at=int(r["created_at"]),
                    updated_at=int(r["updated_at"]),
                )
                for r in rows
            ]

        return []

    def get_messages(self, tenant_id: str, user_email: str, session_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        if not self.enabled():
            return []

        tenant_id = tenant_id or "viva"
        user_email = (user_email or "").strip().lower()

        if self.store == "sqlite":
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT ts, role, content, model, sources_json
                    FROM chat_messages
                    WHERE tenant_id = ? AND user_email = ? AND session_id = ?
                    ORDER BY ts ASC
                    LIMIT ?
                    """,
                    (tenant_id, user_email, session_id, int(limit)),
                ).fetchall()

            messages = []
            for r in rows:
                sources = []
                try:
                    sources = json.loads(r["sources_json"] or "[]")
                except Exception:
                    sources = []
                messages.append(
                    {
                        "ts": int(r["ts"]),
                        "role": r["role"],
                        "content": r["content"],
                        "model": r["model"],
                        "sources": sources,
                    }
                )
            return messages

        return []
