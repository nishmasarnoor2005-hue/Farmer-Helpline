"""
frontend/dashboard.py

Data-access helpers for the admin dashboard.
All queries are read-only; no records are modified here.
"""

import importlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: import the database module (deferred to avoid circular imports)
# ---------------------------------------------------------------------------

def _db():
    import backend.database as _database
    return _database


# ---------------------------------------------------------------------------
# Dashboard metrics
# ---------------------------------------------------------------------------

def get_dashboard_data() -> dict[str, Any]:
    """
    Return aggregated statistics for the dashboard overview panel.

    Keys returned:
      total_sessions       – int
      total_interactions   – int
      avg_total_latency_ms – int (0 if no data)
      by_language          – list of {"language": str, "count": int}
      by_intent            – list of {"intent": str, "count": int}
      error_categories     – list of {"error_category": str, "count": int}
    """
    db = _db()
    try:
        from backend.database import _get_conn  # noqa: PLC0415

        with _get_conn() as conn:
            # Total sessions
            row = conn.execute("SELECT COUNT(*) AS cnt FROM call_sessions").fetchone()
            total_sessions = row["cnt"] if row else 0

            # Total interactions + avg latency
            row = conn.execute(
                "SELECT COUNT(*) AS cnt, AVG(total_latency_ms) AS avg_ms FROM interactions"
            ).fetchone()
            total_interactions = row["cnt"] if row else 0
            avg_total_latency_ms = int(round(row["avg_ms"])) if row and row["avg_ms"] else 0

            # Interactions by language
            rows = conn.execute(
                """
                SELECT language, COUNT(*) AS cnt
                FROM interactions
                WHERE language IS NOT NULL
                GROUP BY language
                ORDER BY cnt DESC
                """
            ).fetchall()
            by_language = [{"language": r["language"], "count": r["cnt"]} for r in rows]

            # Interactions by intent
            rows = conn.execute(
                """
                SELECT intent, COUNT(*) AS cnt
                FROM interactions
                WHERE intent IS NOT NULL
                GROUP BY intent
                ORDER BY cnt DESC
                """
            ).fetchall()
            by_intent = [{"intent": r["intent"], "count": r["cnt"]} for r in rows]

            # Error category counts
            rows = conn.execute(
                """
                SELECT error_category, COUNT(*) AS cnt
                FROM interactions
                WHERE error_category IS NOT NULL
                GROUP BY error_category
                ORDER BY cnt DESC
                """
            ).fetchall()
            error_categories = [
                {"error_category": r["error_category"], "count": r["cnt"]} for r in rows
            ]

        return {
            "total_sessions": total_sessions,
            "total_interactions": total_interactions,
            "avg_total_latency_ms": avg_total_latency_ms,
            "by_language": by_language,
            "by_intent": by_intent,
            "error_categories": error_categories,
        }

    except Exception as exc:
        logger.error("get_dashboard_data failed: %s", exc)
        return {
            "total_sessions": 0,
            "total_interactions": 0,
            "avg_total_latency_ms": 0,
            "by_language": [],
            "by_intent": [],
            "error_categories": [],
        }


# ---------------------------------------------------------------------------
# Paginated interaction history
# ---------------------------------------------------------------------------

def get_interaction_history(page: int = 1, per_page: int = 20) -> dict[str, Any]:
    """
    Return a paginated slice of the interactions table (newest first).

    Returns:
      items      – list of row dicts
      page       – current page (1-based)
      per_page   – page size
      total      – total row count
      total_pages – ceil(total / per_page)
    """
    db = _db()
    try:
        from backend.database import _get_conn  # noqa: PLC0415

        page = max(1, int(page))
        per_page = max(1, int(per_page))
        offset = (page - 1) * per_page

        with _get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM interactions").fetchone()
            total = row["cnt"] if row else 0

            rows = conn.execute(
                """
                SELECT id, session_id, created_at, language, transcript,
                       intent, assistant_response, status,
                       total_latency_ms, error_category
                FROM interactions
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (per_page, offset),
            ).fetchall()
            items = [dict(r) for r in rows]

        import math
        total_pages = math.ceil(total / per_page) if total > 0 else 1

        return {
            "rows": items,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }

    except Exception as exc:
        logger.error("get_interaction_history failed: %s", exc)
        return {"rows": [], "page": page, "per_page": per_page, "total": 0, "total_pages": 1}


# ---------------------------------------------------------------------------
# Service health check
# ---------------------------------------------------------------------------

def service_health() -> dict[str, str]:
    """
    Return a dict of service name → status string ('ok' / 'error' / 'missing').

    Checks:
      db       – executes SELECT 1 against the SQLite file
      gemini   – checks whether GEMINI_API_KEY env var is set (key name only)
      edge_tts – checks whether the edge_tts package is importable
    """
    health: dict[str, str] = {}

    # Database ping
    try:
        from backend.database import _get_conn  # noqa: PLC0415
        with _get_conn() as conn:
            conn.execute("SELECT 1")
        health["db"] = "ok"
    except Exception as exc:
        logger.error("service_health db check failed: %s", exc)
        health["db"] = "error"

    # Gemini API key presence
    health["gemini"] = "ok" if os.environ.get("GEMINI_API_KEY") else "missing"

    # edge-tts importability
    try:
        importlib.import_module("edge_tts")
        health["edge_tts"] = "ok"
    except ImportError:
        health["edge_tts"] = "missing"

    return health
