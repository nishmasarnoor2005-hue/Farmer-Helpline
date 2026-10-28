"""
tests/test_database.py

Isolated tests for backend/database.py.
Each test uses a temporary SQLite file so the production DB is never touched.
"""

import importlib
import sqlite3
import sys
import tempfile
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    """
    Return a fresh database module pointed at a temp file.
    We monkey-patch DB_PATH before calling init_db so every test
    is fully isolated from farmer_helpline.db.
    """
    # Re-import the module fresh each time
    if "backend.database" in sys.modules:
        del sys.modules["backend.database"]

    import backend.database as db_mod
    db_mod.DB_PATH = tmp_path
    return db_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    """Provide a freshly initialised database module backed by a temp file."""
    db_file = tmp_path / "test_helpline.db"
    mod = _make_db(db_file)
    result = mod.init_db()
    assert result is True, "init_db() must return True"
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_creates_all_three_tables(self, db):
        """init_db() must create farmers, call_sessions, and interactions."""
        conn = sqlite3.connect(str(db.DB_PATH))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "farmers" in tables
        assert "call_sessions" in tables
        assert "interactions" in tables

    def test_idempotent(self, db):
        """Calling init_db() twice must not raise or duplicate tables."""
        result = db.init_db()
        assert result is True


class TestCreateSession:
    def test_returns_true(self, db):
        sid = uuid.uuid4().hex
        assert db.create_session(sid) is True

    def test_row_appears_in_db(self, db):
        sid = uuid.uuid4().hex
        db.create_session(sid, channel="browser", language="kn")

        conn = sqlite3.connect(str(db.DB_PATH))
        row = conn.execute(
            "SELECT * FROM call_sessions WHERE id = ?", (sid,)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == sid        # id
        assert row[3] == "browser"  # channel
        assert row[4] == "kn"       # language
        assert row[5] == "active"   # status

    def test_default_channel_is_browser(self, db):
        sid = uuid.uuid4().hex
        db.create_session(sid)

        conn = sqlite3.connect(str(db.DB_PATH))
        row = conn.execute(
            "SELECT channel FROM call_sessions WHERE id = ?", (sid,)
        ).fetchone()
        conn.close()

        assert row[0] == "browser"


class TestLogInteraction:
    def _create_sid(self, db):
        sid = uuid.uuid4().hex
        db.create_session(sid)
        return sid

    def test_returns_true(self, db):
        sid = self._create_sid(db)
        result = db.log_interaction(
            session_id=sid,
            language="kn",
            transcript="ನಮಸ್ಕಾರ",
            intent="greeting",
            assistant_response="Hello farmer",
            status="success",
            latency_dict={
                "total_latency_ms": 1200,
                "gemini_detect_ms": 200,
                "whisper_ms": 400,
                "gemini_reply_ms": 500,
                "tts_ms": 100,
            },
        )
        assert result is True

    def test_persists_correct_fields(self, db):
        sid = self._create_sid(db)
        transcript = "What is the price of tomato?"
        db.log_interaction(
            session_id=sid,
            language="en",
            transcript=transcript,
            intent="market_price",
            assistant_response="Tomato price is ₹20/kg",
            status="success",
            latency_dict={
                "total_latency_ms": 800,
                "gemini_detect_ms": 100,
                "whisper_ms": 300,
                "gemini_reply_ms": 350,
                "tts_ms": 50,
            },
        )

        conn = sqlite3.connect(str(db.DB_PATH))
        row = conn.execute(
            "SELECT * FROM interactions WHERE session_id = ?", (sid,)
        ).fetchone()
        conn.close()

        assert row is not None
        # Column positions in schema:
        # 0=id, 1=session_id, 2=created_at, 3=language, 4=transcript,
        # 5=intent, 6=assistant_response, 7=status, 8=total_latency_ms,
        # 9=gemini_detect_ms, 10=whisper_ms, 11=gemini_reply_ms, 12=tts_ms, 13=error_category
        assert row[1] == sid
        assert row[3] == "en"
        assert row[4] == transcript
        assert row[5] == "market_price"
        assert row[8] == 800   # total_latency_ms
        assert row[9] == 100   # gemini_detect_ms
        assert row[10] == 300  # whisper_ms
        assert row[11] == 350  # gemini_reply_ms
        assert row[12] == 50   # tts_ms

    def test_sql_injection_safety(self, db):
        """Passing a SQL injection string must insert exactly one row, not cause errors."""
        sid = self._create_sid(db)
        malicious = "' OR '1'='1"
        result = db.log_interaction(
            session_id=sid,
            language="en",
            transcript=malicious,
            intent="unknown",
            assistant_response="safe reply",
            status="success",
            latency_dict={"total_latency_ms": 0, "gemini_detect_ms": 0,
                          "whisper_ms": 0, "gemini_reply_ms": 0, "tts_ms": 0},
        )
        assert result is True

        conn = sqlite3.connect(str(db.DB_PATH))
        count = conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE session_id = ?", (sid,)
        ).fetchone()[0]
        conn.close()

        # Injection must not have multiplied rows
        assert count == 1


class TestGetRecentInteractions:
    def test_returns_list_of_dicts(self, db):
        sid = uuid.uuid4().hex
        db.create_session(sid)
        db.log_interaction(
            session_id=sid,
            language="hi",
            transcript="मौसम कैसा है?",
            intent="weather",
            assistant_response="आज मौसम अच्छा है",
            status="success",
            latency_dict={"total_latency_ms": 600, "gemini_detect_ms": 100,
                          "whisper_ms": 200, "gemini_reply_ms": 250, "tts_ms": 50},
        )

        rows = db.get_recent_interactions(limit=10, offset=0)
        assert isinstance(rows, list)
        assert len(rows) >= 1
        row = rows[0]
        assert isinstance(row, dict)
        # Must contain expected keys
        for key in ("id", "session_id", "language", "transcript",
                    "assistant_response", "total_latency_ms"):
            assert key in row, f"Expected key '{key}' missing from result"

    def test_limit_is_respected(self, db):
        sid = uuid.uuid4().hex
        db.create_session(sid)
        for _ in range(5):
            db.log_interaction(
                session_id=sid, language="en", transcript="test",
                intent="unknown", assistant_response="ok", status="success",
                latency_dict={"total_latency_ms": 100, "gemini_detect_ms": 10,
                              "whisper_ms": 30, "gemini_reply_ms": 50, "tts_ms": 10},
            )

        rows = db.get_recent_interactions(limit=3, offset=0)
        assert len(rows) <= 3

    def test_returns_empty_list_on_no_data(self, db):
        # Fresh DB (no interactions inserted yet in this specific check)
        rows = db.get_recent_interactions(limit=50, offset=1000)
        assert rows == []
