"""Persistance des sessions de chat (SQLite).

Remplace le dictionnaire en mémoire `_sessions` : l'historique de
conversation survit aux redémarrages du serveur et peut être ré-hydraté
par le frontend après un reload de page.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chat_history.db")

SESSION_TTL_SECONDS = 86_400  # 24 heures d'inactivité


def _now() -> float:
    return time.time()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                last_access REAL NOT NULL,
                summary_text TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                citations_json TEXT,
                mode TEXT,
                tokens_used INTEGER,
                created_at REAL NOT NULL,
                compacted INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
            """
        )


def get_or_create_session(session_id: Optional[str]) -> str:
    """Crée la session si besoin et met à jour `last_access`. Retourne le session_id."""
    import uuid

    sid = session_id or str(uuid.uuid4())
    now = _now()
    with _connect() as conn:
        row = conn.execute("SELECT session_id FROM sessions WHERE session_id = ?", (sid,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sessions (session_id, created_at, last_access, summary_text) VALUES (?, ?, ?, NULL)",
                (sid, now, now),
            )
        else:
            conn.execute("UPDATE sessions SET last_access = ? WHERE session_id = ?", (now, sid))
    return sid


def get_history_for_llm(session_id: str) -> list[dict[str, str]]:
    """Historique non compacté, format `[{"role": ..., "content": ...}]` pour le générateur."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? AND compacted = 0 ORDER BY id",
            (session_id,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def get_full_history_for_ui(session_id: str) -> list[dict[str, Any]]:
    """Historique complet (compacté ou non) pour ré-hydrater le frontend."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content, citations_json, mode, tokens_used, created_at "
            "FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()

    messages = []
    for r in rows:
        msg: dict[str, Any] = {
            "id": f"db-{r['id']}",
            "role": r["role"],
            "content": r["content"],
            "rawContent": r["content"],
            "timestamp": __import__("datetime").datetime.utcfromtimestamp(r["created_at"]).isoformat() + "Z",
        }
        if r["role"] == "assistant":
            stored_sources = json.loads(r["citations_json"]) if r["citations_json"] else []
            # Reformate {file, page, section, score, content} -> {id, source, snippet, page, content}
            # pour correspondre à la forme produite côté frontend lors de l'envoi d'un message (App.jsx)
            msg["citations"] = [
                {
                    "id": i + 1,
                    "source": s.get("file"),
                    "snippet": s.get("section"),
                    "page": s.get("page"),
                    "content": s.get("content", ""),
                }
                for i, s in enumerate(stored_sources)
            ]
            msg["saved"] = False
        if r["mode"]:
            msg["mode"] = r["mode"]
        messages.append(msg)
    return messages


def get_summary(session_id: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT summary_text FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return row["summary_text"] if row else None


def set_summary(session_id: str, summary_text: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE sessions SET summary_text = ? WHERE session_id = ?", (summary_text, session_id))


def append_message(
    session_id: str,
    role: str,
    content: str,
    citations: Optional[list[dict[str, Any]]] = None,
    mode: Optional[str] = None,
    tokens_used: Optional[int] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, citations_json, mode, tokens_used, created_at, compacted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (
                session_id,
                role,
                content,
                json.dumps(citations) if citations is not None else None,
                mode,
                tokens_used,
                _now(),
            ),
        )


def mark_compacted(session_id: str, message_ids: list[int]) -> None:
    """Marque des messages comme compactés : ils restent en base (affichage UI/export)
    mais ne sont plus envoyés au LLM via `get_history_for_llm`."""
    if not message_ids:
        return
    with _connect() as conn:
        placeholders = ",".join("?" * len(message_ids))
        conn.execute(
            f"UPDATE messages SET compacted = 1 WHERE session_id = ? AND id IN ({placeholders})",
            (session_id, *message_ids),
        )


def get_uncompacted_message_ids(session_id: str) -> list[tuple[int, str, str]]:
    """Retourne `(id, role, content)` des messages non compactés, dans l'ordre."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content FROM messages WHERE session_id = ? AND compacted = 0 ORDER BY id",
            (session_id,),
        ).fetchall()
    return [(r["id"], r["role"], r["content"]) for r in rows]


def clear_session(session_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def cleanup_stale_sessions() -> int:
    """Purge les sessions inactives depuis plus de SESSION_TTL_SECONDS. Retourne le nombre purgé."""
    cutoff = _now() - SESSION_TTL_SECONDS
    with _connect() as conn:
        stale = [r["session_id"] for r in conn.execute("SELECT session_id FROM sessions WHERE last_access < ?", (cutoff,)).fetchall()]
        for sid in stale:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
    return len(stale)
