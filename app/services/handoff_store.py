"""Tiny SQLite store for Intercom mapping, webhook dedupe, and human replies."""
import sqlite3
import time
from contextlib import contextmanager

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS intercom_links (
 session_id TEXT PRIMARY KEY, conversation_id TEXT UNIQUE NOT NULL,
 created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS processed_intercom_events (
 event_id TEXT PRIMARY KEY, received_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS human_replies (
 id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
 intercom_part_id TEXT UNIQUE, body TEXT NOT NULL, created_at REAL NOT NULL);
"""


@contextmanager
def connection():
    conn = sqlite3.connect(config.STATE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def conversation_for(session_id: str):
    with connection() as conn:
        row = conn.execute("SELECT conversation_id FROM intercom_links WHERE session_id=?",
                           (session_id,)).fetchone()
        return row["conversation_id"] if row else None


def session_for(conversation_id: str):
    with connection() as conn:
        row = conn.execute("SELECT session_id FROM intercom_links WHERE conversation_id=?",
                           (conversation_id,)).fetchone()
        return row["session_id"] if row else None


def link(session_id: str, conversation_id: str):
    with connection() as conn:
        conn.execute("INSERT OR REPLACE INTO intercom_links VALUES (?,?,?)",
                     (session_id, conversation_id, time.time()))


def first_event(event_id: str) -> bool:
    if not event_id:
        return True
    with connection() as conn:
        try:
            conn.execute("INSERT INTO processed_intercom_events VALUES (?,?)",
                         (event_id, time.time()))
            return True
        except sqlite3.IntegrityError:
            return False


def save_human_reply(session_id: str, part_id: str, body: str) -> bool:
    """Store a human reply once. Returns True only for the first insert, so
    callers can mirror it into the live transcript without duplicating on
    webhook retries."""
    with connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO human_replies"
            " (session_id,intercom_part_id,body,created_at) VALUES (?,?,?,?)",
            (session_id, part_id or None, body, time.time()))
        return cur.rowcount > 0


def clear_session(session_id: str):
    """Forget a session's human replies and Intercom link (reset button)."""
    with connection() as conn:
        conn.execute("DELETE FROM human_replies WHERE session_id=?",
                     (session_id,))
        conn.execute("DELETE FROM intercom_links WHERE session_id=?",
                     (session_id,))


def replies_after(session_id: str, after_id: int = 0):
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT id,body,created_at FROM human_replies WHERE session_id=? AND id>?"
            " ORDER BY id", (session_id, after_id)).fetchall()]
