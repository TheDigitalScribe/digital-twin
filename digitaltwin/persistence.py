"""Durable persistence for lead capture and unknown questions.

Leads recorded via ``record_user_details`` and unknown questions via
``record_unknown_question`` are stored in a lightweight SQLite-backed store
that never raises: if persistence fails for any reason, the caller falls
back to best-effort logging as before.

Thread-safety: SQLite connections are per-call (opened/closed around each
write) which is safe across the async event loop and cheap for the low write
volume this app generates.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import get_settings
from .logger import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    email TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT 'Name not provided',
    notes TEXT NOT NULL DEFAULT 'Not provided'
);

CREATE TABLE IF NOT EXISTS unknown_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL
);
"""


def _db_path() -> Path | None:
    """Return the configured SQLite file path, or None if persistence is off."""
    settings = get_settings()
    raw = settings.leads_db_path
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        # Resolve relative to the repository root (parent of the package dir).
        path = Path(__file__).resolve().parent.parent / path
    return path


@contextmanager
def _connect() -> Iterator[sqlite3.Connection | None]:
    """Open a connection to the leads DB, initializing schema on first use."""
    path = _db_path()
    if path is None:
        yield None
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def persist_lead(
    email: str, name: str = "Name not provided", notes: str = "Not provided"
) -> bool:
    """Persist a lead. Returns True on success, False when persistence is
    disabled or the write fails (caller may still log)."""
    with _connect() as conn:
        if conn is None:
            logger.debug("Lead persistence disabled; skipping DB write")
            return False
        try:
            conn.execute(
                "INSERT INTO leads (created_at, email, name, notes) VALUES (?, ?, ?, ?)",
                (_now(), email, name, notes),
            )
            logger.info(
                "lead_persisted",
                extra={"event": "lead_persisted", "email": email},
            )
            return True
        except sqlite3.Error as exc:
            logger.error("Failed to persist lead: %s", exc)
            return False


def persist_unknown_question(question: str) -> bool:
    """Persist an unanswered question. Returns True on success."""
    with _connect() as conn:
        if conn is None:
            logger.debug("Question persistence disabled; skipping DB write")
            return False
        try:
            conn.execute(
                "INSERT INTO unknown_questions (created_at, question) VALUES (?, ?)",
                (_now(), question),
            )
            logger.info(
                "unknown_question_persisted",
                extra={"event": "unknown_question_persisted"},
            )
            return True
        except sqlite3.Error as exc:
            logger.error("Failed to persist unknown question: %s", exc)
            return False


def reset_db() -> None:
    """Drop and recreate the tables (used by tests to isolate runs)."""
    with _connect() as conn:
        if conn is None:
            return
        try:
            conn.execute("DROP TABLE IF EXISTS leads")
            conn.execute("DROP TABLE IF EXISTS unknown_questions")
            conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            logger.error("Failed to reset leads DB: %s", exc)


def fetch_all_leads() -> list[dict[str, Any]]:
    """Return all recorded leads, newest first (used by tests/admin)."""
    with _connect() as conn:
        if conn is None:
            return []
        rows = conn.execute(
            "SELECT created_at, email, name, notes FROM leads ORDER BY id DESC"
        ).fetchall()
    return [
        {"created_at": r[0], "email": r[1], "name": r[2], "notes": r[3]}
        for r in rows
    ]