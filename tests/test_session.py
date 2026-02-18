"""Tests for SessionManager: CRUD, append-only event semantics, UUID prefix lookup,
and active session env var detection.

Uses in-memory SQLite -- no disk I/O or API calls.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from objlib.database import Database
from objlib.session.manager import SessionManager, VALID_EVENT_TYPES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_db():
    """Fresh initialized in-memory SQLite database.

    Uses Database.__new__() to bypass __init__ path validation.
    Calls real Database._setup_schema() to test actual schema setup.
    Sets row_factory and foreign_keys BEFORE schema setup.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db = Database.__new__(Database)
    db.conn = conn
    db.db_path = ":memory:"
    db._setup_schema()
    yield db
    conn.close()


@pytest.fixture
def mgr(in_memory_db) -> SessionManager:
    """SessionManager wired to the in-memory database."""
    return SessionManager(in_memory_db.conn)


# ---------------------------------------------------------------------------
# Session CRUD Tests
# ---------------------------------------------------------------------------


class TestSessionCRUD:
    """Test create, get, list operations on sessions."""

    def test_create_session(self, mgr):
        """create() returns a valid UUID string."""
        session_id = mgr.create("My Research")
        # Should be a valid UUID-4 string
        parsed = uuid.UUID(session_id)
        assert parsed.version == 4

    def test_get_session(self, mgr):
        """get_session returns the session with correct name."""
        session_id = mgr.create("Philosophy 101")
        session = mgr.get_session(session_id)
        assert session is not None
        assert session["name"] == "Philosophy 101"
        assert session["id"] == session_id

    def test_get_session_nonexistent(self, mgr):
        """get_session with random UUID returns None."""
        fake_id = str(uuid.uuid4())
        session = mgr.get_session(fake_id)
        assert session is None

    def test_create_multiple_sessions(self, mgr):
        """Multiple sessions all have unique IDs."""
        ids = [mgr.create(f"Session {i}") for i in range(3)]
        assert len(set(ids)) == 3

    def test_create_session_default_name(self, mgr):
        """create() with no name auto-generates a timestamped name."""
        session_id = mgr.create()
        session = mgr.get_session(session_id)
        assert session is not None
        assert session["name"].startswith("Session 20")

    def test_list_sessions(self, mgr):
        """list_sessions returns all created sessions with event counts."""
        mgr.create("First")
        sid2 = mgr.create("Second")
        mgr.add_event(sid2, "search", {"query": "test"})

        sessions = mgr.list_sessions()
        assert len(sessions) == 2

        # Find the one with events
        by_id = {s["id"]: s for s in sessions}
        assert by_id[sid2]["event_count"] == 1


# ---------------------------------------------------------------------------
# Event Semantics Tests
# ---------------------------------------------------------------------------


class TestEventSemantics:
    """Test append-only event logging with type validation."""

    def test_add_event(self, mgr):
        """add_event appends an event with correct type and payload."""
        sid = mgr.create("Events Test")
        mgr.add_event(sid, "search", {"query": "free will"})

        events = mgr.get_events(sid)
        assert len(events) == 1
        assert events[0]["event_type"] == "search"
        assert events[0]["payload"] == {"query": "free will"}

    def test_add_multiple_events(self, mgr):
        """Multiple events are returned in chronological order."""
        sid = mgr.create("Multi")
        mgr.add_event(sid, "search", {"query": "metaphysics"})
        mgr.add_event(sid, "view", {"filename": "opar.txt"})
        mgr.add_event(sid, "note", {"text": "interesting"})

        events = mgr.get_events(sid)
        assert len(events) == 3
        types = [e["event_type"] for e in events]
        assert types == ["search", "view", "note"]

    def test_event_types_valid(self, mgr):
        """All valid event types are accepted without error."""
        sid = mgr.create("Type Check")
        for event_type in sorted(VALID_EVENT_TYPES):
            event_id = mgr.add_event(sid, event_type, {"test": True})
            parsed = uuid.UUID(event_id)
            assert parsed.version == 4

        events = mgr.get_events(sid)
        assert len(events) == len(VALID_EVENT_TYPES)

    def test_event_type_invalid(self, mgr):
        """Invalid event type raises ValueError."""
        sid = mgr.create("Bad Type")
        with pytest.raises(ValueError, match="Invalid event_type"):
            mgr.add_event(sid, "invalid_type", {"bad": True})

    def test_append_only_no_update_method(self, mgr):
        """SessionManager has NO update_event method (append-only per
        decision [04-04])."""
        assert not hasattr(mgr, "update_event")

    def test_append_only_no_delete_event_method(self, mgr):
        """SessionManager has NO delete_event method (events can only be
        added per decision [04-04])."""
        assert not hasattr(mgr, "delete_event")

    def test_append_only_no_modify_method(self, mgr):
        """SessionManager has NO modify_event method."""
        assert not hasattr(mgr, "modify_event")

    def test_event_payload_preserved(self, mgr):
        """Complex payload dict is round-tripped through JSON correctly."""
        sid = mgr.create("Payload")
        payload = {
            "query": "virtue ethics",
            "result_count": 42,
            "nested": {"key": "value"},
            "list": [1, 2, 3],
        }
        mgr.add_event(sid, "search", payload)

        events = mgr.get_events(sid)
        assert events[0]["payload"] == payload


# ---------------------------------------------------------------------------
# UUID Prefix Lookup Tests
# ---------------------------------------------------------------------------


class TestUUIDPrefixLookup:
    """Test find_by_prefix with exact, ambiguous, and no-match cases."""

    def test_find_by_prefix_exact(self, mgr):
        """First 8 chars of UUID uniquely identify the session."""
        sid = mgr.create("Prefix Test")
        prefix = sid[:8]
        result = mgr.find_by_prefix(prefix)
        assert result is not None
        assert result["id"] == sid

    def test_find_by_prefix_ambiguous(self, mgr):
        """When prefix matches 2+ sessions, returns None."""
        # Create sessions until we get two that share a 1-char prefix
        # Force this by creating many sessions
        sessions = [mgr.create(f"S{i}") for i in range(50)]
        # Group by first character
        by_first = {}
        for sid in sessions:
            ch = sid[0]
            by_first.setdefault(ch, []).append(sid)

        # Find a prefix that matches multiple sessions
        ambiguous_prefix = None
        for ch, sids in by_first.items():
            if len(sids) >= 2:
                ambiguous_prefix = ch
                break

        assert ambiguous_prefix is not None, "Need at least 2 sessions sharing first char"
        result = mgr.find_by_prefix(ambiguous_prefix)
        assert result is None

    def test_find_by_prefix_no_match(self, mgr):
        """A prefix matching no sessions returns None."""
        mgr.create("Something")
        result = mgr.find_by_prefix("zzzzzzz")
        assert result is None

    def test_find_by_prefix_full_uuid(self, mgr):
        """Full UUID as prefix returns the session."""
        sid = mgr.create("Full UUID")
        result = mgr.find_by_prefix(sid)
        assert result is not None
        assert result["id"] == sid


# ---------------------------------------------------------------------------
# Active Session Detection Tests
# ---------------------------------------------------------------------------


class TestActiveSessionDetection:
    """Test env-var-based active session detection."""

    def test_active_session_from_env(self, monkeypatch):
        """OBJLIB_SESSION env var is returned as active session ID."""
        fake_id = str(uuid.uuid4())
        monkeypatch.setenv("OBJLIB_SESSION", fake_id)
        assert SessionManager.get_active_session_id() == fake_id

    def test_no_active_session(self, monkeypatch):
        """Without OBJLIB_SESSION, get_active_session_id returns None."""
        monkeypatch.delenv("OBJLIB_SESSION", raising=False)
        assert SessionManager.get_active_session_id() is None
