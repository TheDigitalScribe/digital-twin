"""Tests for the SQLite persistence layer (leads + unknown questions)."""

import pytest

from digitaltwin.config import Settings
from digitaltwin.persistence import (
    fetch_all_leads,
    persist_lead,
    persist_unknown_question,
    reset_db,
)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point the DB at a temp file and start from a clean schema."""
    monkeypatch.setattr(
        "digitaltwin.persistence.get_settings",
        lambda: Settings(leads_db_path=str(tmp_path / "test-leads.db")),
    )
    reset_db()
    yield
    reset_db()


class TestLeadPersistence:
    def test_persist_and_fetch_roundtrip(self, isolated_db):
        assert persist_lead("jane@example.com", "Jane", "wants salary info")
        leads = fetch_all_leads()
        assert len(leads) == 1
        assert leads[0]["email"] == "jane@example.com"
        assert leads[0]["name"] == "Jane"
        assert leads[0]["notes"] == "wants salary info"
        assert leads[0]["created_at"]

    def test_defaults_used_when_not_provided(self, isolated_db):
        persist_lead("bob@example.com")
        lead = fetch_all_leads()[0]
        assert lead["name"] == "Name not provided"
        assert lead["notes"] == "Not provided"

    def test_multiple_leads_newest_first(self, isolated_db):
        persist_lead("a@example.com")
        persist_lead("b@example.com")
        leads = fetch_all_leads()
        assert [l["email"] for l in leads] == ["b@example.com", "a@example.com"]

    def test_unknown_question_persisted(self, isolated_db):
        assert persist_unknown_question("What is your home address?")
        # Round-trip through the DB to confirm it landed.
        import sqlite3

        from digitaltwin.persistence import _db_path

        conn = sqlite3.connect(str(_db_path()))
        rows = conn.execute("SELECT question FROM unknown_questions").fetchall()
        conn.close()
        assert rows == [("What is your home address?",)]

    def test_reset_db_clears_rows(self, isolated_db):
        persist_lead("a@example.com")
        assert len(fetch_all_leads()) == 1
        reset_db()
        assert fetch_all_leads() == []

    def test_disabled_persistence_returns_false(self, monkeypatch):
        # LEADS_DB_PATH empty -> persistence disabled -> returns False,
        # callers fall back to logging/push only.
        monkeypatch.setattr(
            "digitaltwin.persistence.get_settings",
            lambda: Settings(leads_db_path=None),
        )
        assert persist_lead("x@example.com") is False