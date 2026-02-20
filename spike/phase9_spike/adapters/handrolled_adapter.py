"""Hand-rolled FSM adapter implementing FileStateMachineProtocol.

Fallback implementation that does NOT depend on python-statemachine.
Satisfies the same Protocol so all test harness code works unchanged.

This file exists as documented fallback. The primary path uses
StateMachineAdapter (statemachine_adapter.py).
"""

from datetime import datetime, timezone

import aiosqlite

from spike.phase9_spike.db import execute_with_retry
from spike.phase9_spike.event_log import EventCollector
from spike.phase9_spike.exceptions import (
    GuardRejectedError,
    StaleTransitionError,
    TransitionNotAllowedError,
)
from spike.phase9_spike.states import EVENTS


class HandRolledAdapter:
    """Hand-rolled async FSM satisfying FileStateMachineProtocol.

    No external library dependency. Guards, transitions, and DB writes
    are all handled inline with explicit control flow.

    Ephemeral: create from DB state, use for one transition, discard.
    """

    def __init__(
        self,
        file_id: str,
        db_path: str,
        initial_state: str,
        initial_version: int,
        event_collector: EventCollector | None = None,
    ):
        self._file_id = file_id
        self._db_path = db_path
        self._state = initial_state
        self._version = initial_version
        self._event_collector = event_collector

    @property
    def current_state(self) -> str:
        """Current FSM state as a string."""
        return self._state

    async def trigger(self, event: str, **kwargs) -> None:
        """Trigger a state transition with guard check and OCC write."""
        edge = EVENTS.get(event)
        if edge is None:
            raise TransitionNotAllowedError(
                f"Unknown event: {event}"
            )

        from_state, to_state = edge
        if self._state != from_state:
            if self._event_collector:
                self._event_collector.emit(
                    file_id=self._file_id,
                    from_state=self._state,
                    to_state=to_state,
                    event=event,
                    outcome="rejected",
                    guard_result=False,
                    error=f"Current state '{self._state}' != required '{from_state}'",
                )
            raise TransitionNotAllowedError(
                f"Event '{event}' requires state '{from_state}', "
                f"but current state is '{self._state}'"
            )

        # Run async guard: check DB version matches expected
        try:
            guard_ok = await self._check_version_guard()
        except Exception as e:
            if self._event_collector:
                self._event_collector.emit(
                    file_id=self._file_id,
                    from_state=from_state,
                    to_state=to_state,
                    event=event,
                    outcome="failed",
                    guard_result=None,
                    error=str(e),
                )
            raise

        if not guard_ok:
            if self._event_collector:
                self._event_collector.emit(
                    file_id=self._file_id,
                    from_state=from_state,
                    to_state=to_state,
                    event=event,
                    outcome="rejected",
                    guard_result=False,
                    error="OCC version mismatch in guard",
                )
            raise GuardRejectedError(
                f"Guard rejected: version mismatch for {self._file_id}"
            )

        # Execute OCC UPDATE
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            rowcount = await execute_with_retry(
                self._db_path,
                """UPDATE files
                   SET gemini_state = ?,
                       version = version + 1,
                       gemini_state_updated_at = ?
                   WHERE file_path = ?
                     AND gemini_state = ?
                     AND version = ?""",
                (to_state, now_iso, self._file_id, from_state, self._version),
            )
        except Exception as e:
            if self._event_collector:
                self._event_collector.emit(
                    file_id=self._file_id,
                    from_state=from_state,
                    to_state=to_state,
                    event=event,
                    outcome="failed",
                    guard_result=True,
                    error=str(e),
                )
            raise

        if rowcount == 0:
            if self._event_collector:
                self._event_collector.emit(
                    file_id=self._file_id,
                    from_state=from_state,
                    to_state=to_state,
                    event=event,
                    outcome="rejected",
                    guard_result=True,
                    error="OCC conflict (rowcount=0)",
                )
            raise StaleTransitionError(
                f"OCC conflict: file {self._file_id} was modified concurrently"
            )

        # Update in-memory state to match DB
        self._state = to_state
        self._version += 1

        if self._event_collector:
            self._event_collector.emit(
                file_id=self._file_id,
                from_state=from_state,
                to_state=to_state,
                event=event,
                outcome="success",
                guard_result=True,
            )

    async def can_trigger(self, event: str, **kwargs) -> bool:
        """Check if the event can be triggered for the current state."""
        edge = EVENTS.get(event)
        if edge is None:
            return False
        from_state, _to_state = edge
        return self._state == from_state

    async def _check_version_guard(self) -> bool:
        """Async guard: verify OCC version in DB matches expected."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT version FROM files WHERE file_path = ?",
                (self._file_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return False
            return row[0] == self._version
