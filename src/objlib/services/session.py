"""Session service facade wrapping SessionManager internals.

Provides async CRUD for research sessions with append-only event
logging. All SQLite operations are wrapped in asyncio.to_thread()
with Database connections opened and closed within the sync function.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class SessionService:
    """Async facade for research session management.

    Wraps SessionManager operations for creating sessions, adding
    events, and querying session history. Database connections are
    scoped to each operation.

    Usage::

        svc = SessionService("data/library.db")
        session_id = await svc.create_session("My Research")
        event_id = await svc.add_event(session_id, "search", {"query": "rights"})
        events = await svc.get_events(session_id)
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def create_session(self, name: str | None = None) -> str:
        """Create a new research session.

        Args:
            name: Optional session name. Auto-generates timestamped
                  name if None.

        Returns:
            The session UUID string.
        """

        def _create() -> str:
            from objlib.database import Database
            from objlib.session.manager import SessionManager

            with Database(self._db_path) as db:
                mgr = SessionManager(db.conn)
                return mgr.create(name)

        return await asyncio.to_thread(_create)

    async def add_event(
        self, session_id: str, event_type: str, payload: dict
    ) -> str:
        """Append an event to a session.

        Args:
            session_id: UUID of the session.
            event_type: One of the valid event types (search, view,
                        synthesize, note, error, bookmark).
            payload: Event-specific data dict.

        Returns:
            The event UUID string.

        Raises:
            ValueError: If event_type is not valid.
        """

        def _add() -> str:
            from objlib.database import Database
            from objlib.session.manager import SessionManager

            with Database(self._db_path) as db:
                mgr = SessionManager(db.conn)
                return mgr.add_event(session_id, event_type, payload)

        return await asyncio.to_thread(_add)

    async def list_sessions(self) -> list[dict]:
        """List all sessions with event counts.

        Returns:
            List of session dicts with id, name, created_at,
            updated_at, event_count keys. Most recent first.
        """

        def _list() -> list[dict]:
            from objlib.database import Database
            from objlib.session.manager import SessionManager

            with Database(self._db_path) as db:
                mgr = SessionManager(db.conn)
                return mgr.list_sessions()

        return await asyncio.to_thread(_list)

    async def get_events(self, session_id: str) -> list[dict]:
        """Get all events for a session in chronological order.

        Args:
            session_id: UUID of the session.

        Returns:
            List of event dicts with id, session_id, event_type,
            payload, created_at keys.
        """

        def _get() -> list[dict]:
            from objlib.database import Database
            from objlib.session.manager import SessionManager

            with Database(self._db_path) as db:
                mgr = SessionManager(db.conn)
                return mgr.get_events(session_id)

        return await asyncio.to_thread(_get)

    async def get_session(self, session_id: str) -> dict | None:
        """Get a single session by UUID or prefix.

        Args:
            session_id: Full UUID or prefix of a session.

        Returns:
            Session dict with id, name, created_at, updated_at keys,
            or None if not found (or ambiguous prefix).
        """

        def _get() -> dict | None:
            from objlib.database import Database
            from objlib.session.manager import SessionManager

            with Database(self._db_path) as db:
                mgr = SessionManager(db.conn)
                # Try exact match first
                session = mgr.get_session(session_id)
                if session is not None:
                    return session
                # Fall back to prefix lookup
                return mgr.find_by_prefix(session_id)

        return await asyncio.to_thread(_get)
