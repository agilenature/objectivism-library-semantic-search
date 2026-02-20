"""python-statemachine adapter implementing FileStateMachineProtocol.

Wraps python-statemachine's StateMachine class. Each adapter instance is
ephemeral (locked decision #6): created from DB state, used for ONE
transition, then discarded. The DB is the sole source of truth (locked
decision #5).
"""

from datetime import datetime, timezone

import aiosqlite
from statemachine import State, StateMachine
from statemachine.exceptions import TransitionNotAllowed

from spike.phase9_spike.db import execute_with_retry, read_file_state
from spike.phase9_spike.event_log import EventCollector
from spike.phase9_spike.exceptions import (
    GuardRejectedError,
    StaleTransitionError,
    TransitionNotAllowedError,
)
from spike.phase9_spike.states import EVENTS


# ---------------------------------------------------------------------------
# Internal python-statemachine class
# ---------------------------------------------------------------------------

class FileLifecycleSM(StateMachine):
    """python-statemachine FSM for the file lifecycle.

    States: untracked -> uploading -> processing -> indexed | failed
    """

    untracked = State("untracked", initial=True, value="untracked")
    uploading = State("uploading", value="uploading")
    processing = State("processing", value="processing")
    indexed = State("indexed", final=True, value="indexed")
    failed = State("failed", final=True, value="failed")

    # Transitions with guards
    start_upload = untracked.to(uploading, cond="cond_not_stale")
    complete_upload = uploading.to(processing, cond="cond_not_stale")
    complete_processing = processing.to(indexed, cond="cond_not_stale")
    fail_upload = uploading.to(failed)
    fail_processing = processing.to(failed)

    async def cond_not_stale(
        self, file_id: str, db_path: str, expected_version: int
    ) -> bool:
        """Async guard: verify OCC version before allowing transition."""
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT version FROM files WHERE file_path = ?", (file_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return False
            return row[0] == expected_version

    async def on_enter_state(self, target: State, source: State,
                             file_id: str = None, db_path: str = None,
                             expected_version: int = None, **kwargs):
        """Persist state change to DB on every state entry.

        Uses OCC UPDATE pattern: only succeeds if the expected state and
        version still match in DB. If rowcount==0, another coroutine won
        the race.

        Parameters are optional because this fires during activate_initial_state()
        when no trigger kwargs are available. We skip the DB write in that case.
        """
        # Skip writing on initial state activation (no real transition)
        # During activation, source is an empty placeholder state with value=None
        if source is None or source.value is None:
            return

        # Also skip if trigger kwargs are not provided
        if file_id is None or db_path is None or expected_version is None:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        source_value = source.value if hasattr(source, "value") else str(source)
        target_value = target.value if hasattr(target, "value") else str(target)

        rowcount = await execute_with_retry(
            db_path,
            """UPDATE files
               SET gemini_state = ?,
                   version = version + 1,
                   gemini_state_updated_at = ?
               WHERE file_path = ?
                 AND gemini_state = ?
                 AND version = ?""",
            (target_value, now_iso, file_id, source_value, expected_version),
        )
        if rowcount == 0:
            raise StaleTransitionError(
                f"OCC conflict: file {file_id} was modified concurrently "
                f"(expected state={source_value}, version={expected_version})"
            )


# ---------------------------------------------------------------------------
# Adapter (satisfies FileStateMachineProtocol)
# ---------------------------------------------------------------------------

class StateMachineAdapter:
    """Adapter wrapping FileLifecycleSM to satisfy FileStateMachineProtocol.

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
        self._initial_state = initial_state
        self._initial_version = initial_version
        self._event_collector = event_collector
        self._activated = False

        # Create the internal SM at the correct initial state
        self._sm = FileLifecycleSM(start_value=initial_state)

    @property
    def current_state(self) -> str:
        """Current FSM state as a string."""
        try:
            return self._sm.current_state_value
        except Exception:
            # Before activation, the library may not have a current state
            return self._initial_state

    async def trigger(self, event: str, **kwargs) -> None:
        """Trigger a state transition.

        Emits event log entries for success/rejection/failure.
        """
        if not self._activated:
            await self._sm.activate_initial_state()
            self._activated = True

        from_state = self.current_state

        # Determine target state from event name
        edge = EVENTS.get(event)
        to_state = edge[1] if edge else "unknown"

        try:
            await self._sm.send(
                event,
                file_id=self._file_id,
                db_path=self._db_path,
                expected_version=self._initial_version,
                **kwargs,
            )

            # Success
            if self._event_collector:
                self._event_collector.emit(
                    file_id=self._file_id,
                    from_state=from_state,
                    to_state=to_state,
                    event=event,
                    outcome="success",
                    guard_result=True,
                )

        except TransitionNotAllowed as e:
            # Guard returned False or invalid event for current state
            if self._event_collector:
                self._event_collector.emit(
                    file_id=self._file_id,
                    from_state=from_state,
                    to_state=to_state,
                    event=event,
                    outcome="rejected",
                    guard_result=False,
                    error=str(e),
                )
            raise GuardRejectedError(str(e)) from e

        except StaleTransitionError:
            # OCC conflict in on_enter_state
            if self._event_collector:
                self._event_collector.emit(
                    file_id=self._file_id,
                    from_state=from_state,
                    to_state=to_state,
                    event=event,
                    outcome="rejected",
                    guard_result=True,
                    error="OCC conflict",
                )
            raise

        except Exception as e:
            # Unexpected error
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

    async def can_trigger(self, event: str, **kwargs) -> bool:
        """Check if the event can be triggered for the current state."""
        edge = EVENTS.get(event)
        if edge is None:
            return False
        from_state, _to_state = edge
        return self.current_state == from_state
