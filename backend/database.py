"""
backend/database.py

SQLite persistence layer for the AI Farmer Helpline.
All tables are created with IF NOT EXISTS so existing records are preserved.
All queries use parameterised statements — no string interpolation.
"""

import sqlite3
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resolved DB path: <project-root>/farmer_helpline.db
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).parent.parent / "farmer_helpline.db"


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> bool:
    """
    Create all tables if they don't already exist.
    Existing data is never touched.
    Returns True on success, False on failure.
    """
    try:
        with _get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS farmers (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    name     TEXT,
                    mobile   TEXT,
                    location TEXT,
                    language TEXT,
                    crop     TEXT
                );

                CREATE TABLE IF NOT EXISTS call_sessions (
                    id         TEXT    PRIMARY KEY,
                    created_at TEXT,
                    ended_at   TEXT,
                    channel    TEXT    DEFAULT 'browser',
                    language   TEXT,
                    status     TEXT
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id                 TEXT    PRIMARY KEY,
                    session_id         TEXT    REFERENCES call_sessions(id),
                    created_at         TEXT,
                    language           TEXT,
                    transcript         TEXT,
                    intent             TEXT    DEFAULT 'unknown',
                    assistant_response TEXT,
                    status             TEXT,
                    total_latency_ms   INTEGER,
                    gemini_detect_ms   INTEGER,
                    whisper_ms         INTEGER,
                    gemini_reply_ms    INTEGER,
                    tts_ms             INTEGER,
                    error_category     TEXT
                );
            """)
        logger.info("DB initialised at %s", DB_PATH)
        return True
    except Exception as exc:
        logger.error("init_db failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_session(session_id: str, channel: str = "browser", language: str = None) -> bool:
    """
    Insert a new call_sessions row.
    Returns True on success, False on failure.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO call_sessions (id, created_at, channel, language, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, now, channel, language, "active"),
            )
        return True
    except Exception as exc:
        logger.error("create_session failed (session_id=%s): %s", session_id, exc)
        return False


def end_session(session_id: str) -> bool:
    """
    Mark a session as ended.
    Returns True on success, False on failure.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        with _get_conn() as conn:
            conn.execute(
                """
                UPDATE call_sessions
                SET ended_at = ?, status = 'ended'
                WHERE id = ?
                """,
                (now, session_id),
            )
        return True
    except Exception as exc:
        logger.error("end_session failed (session_id=%s): %s", session_id, exc)
        return False


# ---------------------------------------------------------------------------
# Interaction logging
# ---------------------------------------------------------------------------

def log_interaction(
    session_id: str,
    language: str,
    transcript: str,
    intent: str,
    assistant_response: str,
    status: str,
    latency_dict: dict,
    error_category: str = None,
) -> bool:
    """
    Persist a single voice exchange to the interactions table.
    latency_dict keys: total_latency_ms, gemini_detect_ms, whisper_ms,
                       gemini_reply_ms, tts_ms
    Returns True on success, False on failure (never raises).
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        interaction_id = uuid.uuid4().hex
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO interactions (
                    id, session_id, created_at, language,
                    transcript, intent, assistant_response, status,
                    total_latency_ms, gemini_detect_ms, whisper_ms,
                    gemini_reply_ms, tts_ms, error_category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction_id,
                    session_id,
                    now,
                    language,
                    transcript,
                    intent or "unknown",
                    assistant_response,
                    status,
                    latency_dict.get("total_latency_ms"),
                    latency_dict.get("gemini_detect_ms"),
                    latency_dict.get("whisper_ms"),
                    latency_dict.get("gemini_reply_ms"),
                    latency_dict.get("tts_ms"),
                    error_category,
                ),
            )
        return True
    except Exception as exc:
        logger.error("log_interaction failed (session_id=%s): %s", session_id, exc)
        return False


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_session_stats() -> dict:
    """
    Return aggregate statistics across all sessions.
    Returns a dict with keys: total_sessions, active_sessions,
    total_interactions, avg_latency_ms.
    Returns empty dict on failure.
    """
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM call_sessions"
            ).fetchone()
            total_sessions = row["cnt"] if row else 0

            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM call_sessions WHERE status = 'active'"
            ).fetchone()
            active_sessions = row["cnt"] if row else 0

            row = conn.execute(
                "SELECT COUNT(*) AS cnt, AVG(total_latency_ms) AS avg_ms FROM interactions"
            ).fetchone()
            total_interactions = row["cnt"] if row else 0
            avg_latency_ms = round(row["avg_ms"]) if row and row["avg_ms"] else 0

        return {
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "total_interactions": total_interactions,
            "avg_latency_ms": avg_latency_ms,
        }
    except Exception as exc:
        logger.error("get_session_stats failed: %s", exc)
        return {}


def get_recent_interactions(limit: int = 50, offset: int = 0) -> list:
    """
    Return the most recent interactions as a list of dicts.
    Returns an empty list on failure.
    """
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM interactions
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("get_recent_interactions failed: %s", exc)
        return []
