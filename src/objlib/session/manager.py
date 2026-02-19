"""Session manager for research workflow tracking.

Provides CRUD operations for research sessions, append-only event logging
(search, view, synthesize, note, error), Rich timeline display for resume,
and Markdown export for sharing research notes.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = frozenset({"search", "view", "synthesize", "note", "error", "bookmark"})

# Icons for timeline display
EVENT_ICONS = {
    "search": "[bold cyan]search[/bold cyan]",
    "view": "[bold green]view[/bold green]",
    "synthesize": "[bold magenta]synthesize[/bold magenta]",
    "note": "[bold yellow]note[/bold yellow]",
    "error": "[bold red]error[/bold red]",
    "bookmark": "[bold blue]bookmark[/bold blue]",
}


class SessionManager:
    """Manages research sessions with append-only event logging.

    Operates on the sessions and session_events tables created by
    schema V6 migration. Takes a sqlite3.Connection (from Database.conn).

    Usage:
        from objlib.session import SessionManager
        mgr = SessionManager(db.conn)
        sid = mgr.create("My Research")
        mgr.add_event(sid, "search", {"query": "free will"})
        mgr.display_timeline(sid)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, name: str | None = None) -> str:
        """Create a new research session.

        Args:
            name: Optional session name. If None, auto-generates a
                  timestamped name like "Session 2026-02-18 14:30".

        Returns:
            The session UUID string.
        """
        session_id = str(uuid4())
        if name is None:
            name = f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        with self._conn:
            self._conn.execute(
                "INSERT INTO sessions (id, name) VALUES (?, ?)",
                (session_id, name),
            )

        logger.info("Created session %s: %s", session_id[:8], name)
        return session_id

    def list_sessions(self) -> list[dict]:
        """List all sessions with event counts.

        Returns:
            List of dicts with keys: id, name, created_at, updated_at,
            event_count. Ordered by updated_at descending (most recent first).
        """
        rows = self._conn.execute(
            """SELECT s.id, s.name, s.created_at, s.updated_at,
                      COUNT(e.id) as event_count
               FROM sessions s
               LEFT JOIN session_events e ON s.id = e.session_id
               GROUP BY s.id
               ORDER BY s.updated_at DESC"""
        ).fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "event_count": row["event_count"],
            }
            for row in rows
        ]

    def add_event(
        self, session_id: str, event_type: str, payload: dict
    ) -> str:
        """Append an event to a session (append-only).

        Args:
            session_id: UUID of the session.
            event_type: One of: search, view, synthesize, note, error.
            payload: Event-specific data dict (serialized as JSON).

        Returns:
            The event UUID string.

        Raises:
            ValueError: If event_type is not valid.
        """
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type '{event_type}'. "
                f"Valid types: {', '.join(sorted(VALID_EVENT_TYPES))}"
            )

        event_id = str(uuid4())
        payload_json = json.dumps(payload)

        with self._conn:
            self._conn.execute(
                """INSERT INTO session_events
                   (id, session_id, event_type, payload_json)
                   VALUES (?, ?, ?, ?)""",
                (event_id, session_id, event_type, payload_json),
            )
            self._conn.execute(
                """UPDATE sessions
                   SET updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
                   WHERE id = ?""",
                (session_id,),
            )

        return event_id

    def get_events(self, session_id: str) -> list[dict]:
        """Get all events for a session in chronological order.

        Args:
            session_id: UUID of the session.

        Returns:
            List of dicts with keys: id, session_id, event_type, payload,
            created_at. Payload is parsed from JSON.
        """
        rows = self._conn.execute(
            """SELECT id, session_id, event_type, payload_json, created_at
               FROM session_events
               WHERE session_id = ?
               ORDER BY created_at ASC""",
            (session_id,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_session(self, session_id: str) -> dict | None:
        """Get session metadata by ID.

        Args:
            session_id: UUID of the session.

        Returns:
            Dict with id, name, created_at, updated_at keys, or None if
            session not found.
        """
        row = self._conn.execute(
            "SELECT id, name, created_at, updated_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def display_timeline(
        self, session_id: str, console: Console | None = None
    ) -> None:
        """Display a Rich-formatted timeline of session events.

        Args:
            session_id: UUID of the session.
            console: Optional Rich Console instance. Creates one if None.

        Raises:
            ValueError: If session not found.
        """
        if console is None:
            console = Console()

        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        events = self.get_events(session_id)

        # Session header panel
        header = Text()
        header.append(session["name"], style="bold")
        header.append(f"\nCreated: {session['created_at']}")
        header.append(f"\nEvents: {len(events)}")
        console.print(Panel(header, title="Research Session", border_style="blue"))

        if not events:
            console.print("[dim]No events recorded.[/dim]")
            return

        # Event timeline
        for event in events:
            event_type = event["event_type"]
            payload = event["payload"]
            timestamp = event.get("created_at", "")
            icon = EVENT_ICONS.get(event_type, event_type)

            # Format based on event type
            if event_type == "search":
                query = payload.get("query", "")
                result_count = payload.get("result_count")
                detail = f"[dim]query:[/dim] {query}"
                if result_count is not None:
                    detail += f" [dim]({result_count} results)[/dim]"
            elif event_type == "view":
                filename = payload.get("filename", "")
                detail = f"[dim]viewed:[/dim] {filename}"
            elif event_type == "synthesize":
                query = payload.get("query", "")
                detail = f"[dim]synthesis:[/dim] {query}"
            elif event_type == "note":
                text = payload.get("text", "")
                detail = f"[italic]{text}[/italic]"
            elif event_type == "error":
                message = payload.get("message", "")
                detail = f"[red]error:[/red] {message}"
            else:
                detail = json.dumps(payload)

            # Compact timestamp (time only if same day)
            time_str = ""
            if timestamp:
                time_str = f"[dim]{timestamp}[/dim] "

            console.print(f"  {time_str}{icon}  {detail}")

    def export_markdown(
        self, session_id: str, output_path: Path | str | None = None
    ) -> Path:
        """Export session as a Markdown research document.

        Args:
            session_id: UUID of the session.
            output_path: Optional output file path. Defaults to
                         session_{id[:8]}.md in the current directory.

        Returns:
            Path to the written Markdown file.

        Raises:
            ValueError: If session not found.
        """
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        events = self.get_events(session_id)

        lines: list[str] = []
        lines.append(f"# Research Session: {session['name']}")
        lines.append("")
        lines.append(f"**Created:** {session['created_at']}")
        lines.append(f"**Last updated:** {session['updated_at']}")
        lines.append("")

        if not events:
            lines.append("No events recorded.")
        else:
            lines.append("---")
            lines.append("")

            for event in events:
                event_type = event["event_type"]
                payload = event["payload"]
                timestamp = event.get("created_at", "")

                if event_type == "search":
                    query = payload.get("query", "")
                    lines.append(f"### Search: \"{query}\"")
                    result_count = payload.get("result_count")
                    if result_count is not None:
                        lines.append(f"*{result_count} results*")
                elif event_type == "view":
                    filename = payload.get("filename", "")
                    lines.append(f"### Viewed: {filename}")
                elif event_type == "synthesize":
                    query = payload.get("query", "")
                    lines.append(f"### Synthesis: \"{query}\"")
                elif event_type == "note":
                    text = payload.get("text", "")
                    lines.append(f"> {text}")
                elif event_type == "error":
                    message = payload.get("message", "")
                    lines.append(f"**Error:** {message}")

                if timestamp:
                    lines.append(f"*{timestamp}*")
                lines.append("")

        # Determine output path
        if output_path is None:
            output_path = Path(f"session_{session_id[:8]}.md")
        else:
            output_path = Path(output_path)

        output_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Exported session to %s", output_path)
        return output_path

    def find_by_prefix(self, prefix: str) -> dict | None:
        """Find a session by ID prefix.

        Enables short ID lookups (e.g., "a3f2" instead of full UUID).

        Args:
            prefix: Start of a session UUID.

        Returns:
            Session dict if exactly one match found, None if zero or
            multiple matches (ambiguous).
        """
        rows = self._conn.execute(
            "SELECT id, name, created_at, updated_at FROM sessions WHERE id LIKE ? || '%' LIMIT 2",
            (prefix,),
        ).fetchall()

        if len(rows) != 1:
            return None

        row = rows[0]
        return {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def delete(self, session_id: str) -> bool:
        """Delete a session and all its events.

        Args:
            session_id: UUID of the session to delete.

        Returns:
            True if the session existed and was deleted, False otherwise.
        """
        session = self.get_session(session_id)
        if session is None:
            return False

        with self._conn:
            self._conn.execute(
                "DELETE FROM session_events WHERE session_id = ?",
                (session_id,),
            )
            self._conn.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )

        logger.info("Deleted session %s", session_id[:8])
        return True

    @staticmethod
    def get_active_session_id() -> str | None:
        """Check for an active session via the OBJLIB_SESSION env var.

        Returns:
            The session ID string from OBJLIB_SESSION, or None if not set.
        """
        return os.environ.get("OBJLIB_SESSION")
