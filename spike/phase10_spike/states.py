"""Extended FSM class with Phase 10 transitions (reset, retry, fail_reset).

CRITICAL: NO final=True on any state. python-statemachine raises
InvalidDefinition if final states have outgoing transitions, and Phase 10
needs reset (indexed -> untracked) and retry (failed -> untracked).

This is a standalone FSM definition for Phase 10 spike -- it does NOT modify
Phase 9's states.py or statemachine_adapter.py.
"""

from datetime import datetime, timezone

import aiosqlite
from statemachine import State, StateMachine

from spike.phase9_spike.db import execute_with_retry
from spike.phase9_spike.exceptions import StaleTransitionError


# ---------------------------------------------------------------------------
# Valid edges and events (extended from Phase 9)
# ---------------------------------------------------------------------------

VALID_STATES = frozenset({
    "untracked", "uploading", "processing", "indexed", "failed",
})

VALID_EDGES = frozenset({
    ("untracked", "uploading"),
    ("uploading", "processing"),
    ("processing", "indexed"),
    ("uploading", "failed"),
    ("processing", "failed"),
    # Phase 10 additions
    ("indexed", "untracked"),   # reset
    ("failed", "untracked"),    # retry
    ("indexed", "failed"),      # fail_reset
})

EVENTS = {
    "start_upload": ("untracked", "uploading"),
    "complete_upload": ("uploading", "processing"),
    "complete_processing": ("processing", "indexed"),
    "fail_upload": ("uploading", "failed"),
    "fail_processing": ("processing", "failed"),
    # Phase 10 additions
    "reset": ("indexed", "untracked"),
    "retry": ("failed", "untracked"),
    "fail_reset": ("indexed", "failed"),
}


# ---------------------------------------------------------------------------
# python-statemachine FSM class (extended for Phase 10)
# ---------------------------------------------------------------------------

class FileLifecycleSM(StateMachine):
    """File lifecycle FSM with reset/retry/fail_reset transitions.

    No final states -- all states can have outgoing transitions.
    5 states, 8 transitions.
    """

    untracked = State("untracked", initial=True, value="untracked")
    uploading = State("uploading", value="uploading")
    processing = State("processing", value="processing")
    indexed = State("indexed", value="indexed")
    failed = State("failed", value="failed")

    # Original transitions (with guards)
    start_upload = untracked.to(uploading, cond="cond_not_stale")
    complete_upload = uploading.to(processing, cond="cond_not_stale")
    complete_processing = processing.to(indexed, cond="cond_not_stale")
    fail_upload = uploading.to(failed)
    fail_processing = processing.to(failed)

    # Phase 10 transitions
    reset = indexed.to(untracked)
    retry = failed.to(untracked)
    fail_reset = indexed.to(failed)

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

    async def on_enter_state(
        self,
        target: State,
        source: State,
        file_id: str = None,
        db_path: str = None,
        expected_version: int = None,
        **kwargs,
    ):
        """Persist state change to DB on every state entry.

        Uses OCC UPDATE pattern: only succeeds if the expected state and
        version still match in DB. If rowcount==0, another coroutine won
        the race.

        Parameters are optional because this fires during activate_initial_state()
        when no trigger kwargs are available. We skip the DB write in that case.
        """
        # Skip writing on initial state activation (no real transition)
        if source is None or source.value is None:
            return

        # Skip if trigger kwargs are not provided
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
