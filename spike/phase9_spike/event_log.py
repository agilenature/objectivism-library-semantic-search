"""Structured JSON event log for transition attempts.

Every transition attempt emits a JSON record with attempt_id, file_id,
from_state, to_state, guard_result, and outcome. The EventCollector stores
events in a list for test assertions (instead of only printing to stdout).
"""

import json
import uuid
from datetime import datetime, timezone


def emit_event(
    file_id: str,
    from_state: str,
    to_state: str,
    event: str,
    outcome: str,  # "success" | "rejected" | "failed"
    guard_result: bool | None = None,
    error: str | None = None,
) -> dict:
    """Emit and return a structured JSON event record.

    Prints to stdout for harness capture and returns the dict for in-process use.
    """
    record = {
        "attempt_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "file_id": file_id,
        "event": event,
        "from_state": from_state,
        "to_state": to_state,
        "guard_result": guard_result,
        "outcome": outcome,
        "error": error,
    }
    print(json.dumps(record))
    return record


class EventCollector:
    """Collects structured event records in-memory for test assertions.

    Use instead of (or in addition to) stdout logging when tests need
    to inspect event data programmatically.
    """

    def __init__(self):
        self.events: list[dict] = []

    def emit(
        self,
        file_id: str,
        from_state: str,
        to_state: str,
        event: str,
        outcome: str,
        guard_result: bool | None = None,
        error: str | None = None,
    ) -> dict:
        """Record an event and return the record dict."""
        record = {
            "attempt_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "file_id": file_id,
            "event": event,
            "from_state": from_state,
            "to_state": to_state,
            "guard_result": guard_result,
            "outcome": outcome,
            "error": error,
        }
        self.events.append(record)
        return record

    def successes(self) -> list[dict]:
        """Return events with outcome='success'."""
        return [e for e in self.events if e["outcome"] == "success"]

    def rejections(self) -> list[dict]:
        """Return events with outcome='rejected'."""
        return [e for e in self.events if e["outcome"] == "rejected"]

    def failures(self) -> list[dict]:
        """Return events with outcome='failed'."""
        return [e for e in self.events if e["outcome"] == "failed"]

    def for_file(self, file_id: str) -> list[dict]:
        """Return all events for a specific file."""
        return [e for e in self.events if e["file_id"] == file_id]

    def clear(self):
        """Clear all collected events."""
        self.events.clear()
