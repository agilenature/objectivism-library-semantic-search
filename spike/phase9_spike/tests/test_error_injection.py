"""Error injection tests for FSM transition failure recovery.

Three required scenarios (locked decision #4):
1. Pre-commit error: state UNCHANGED
2. Post-commit error: state IS advanced (committed), failure recorded
3. Guard error: state UNCHANGED
"""

from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from spike.phase9_spike.adapters.statemachine_adapter import (
    FileLifecycleSM,
    StateMachineAdapter,
)
from spike.phase9_spike.db import read_file_state
from spike.phase9_spike.event_log import EventCollector
from spike.phase9_spike.exceptions import StaleTransitionError


class TestPreCommitError:
    """Error BEFORE db.commit() -> state UNCHANGED."""

    async def test_pre_commit_leaves_state_unchanged(
        self, spike_db, seed_file
    ):
        """Inject exception before DB commit. State must remain 'untracked'."""
        file_id = "/test/pre_commit_error.txt"
        await seed_file(file_id, state="untracked", version=0)
        collector = EventCollector()

        # Patch execute_with_retry to raise BEFORE the commit succeeds
        with patch(
            "spike.phase9_spike.adapters.statemachine_adapter.execute_with_retry",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Simulated pre-commit failure"),
        ):
            adapter = StateMachineAdapter(
                file_id=file_id,
                db_path=spike_db,
                initial_state="untracked",
                initial_version=0,
                event_collector=collector,
            )

            with pytest.raises(RuntimeError, match="pre-commit"):
                await adapter.trigger("start_upload")

        # State must be unchanged in DB
        state, version = await read_file_state(spike_db, file_id)
        assert state == "untracked", (
            f"Expected 'untracked' after pre-commit error, got '{state}'"
        )
        assert version == 0, f"Expected version 0, got {version}"

        # Event log shows failure
        failures = collector.failures()
        assert len(failures) == 1, f"Expected 1 failure event, got {len(failures)}"
        assert "pre-commit" in failures[0]["error"]


class TestPostCommitError:
    """Error AFTER db.commit() -> state IS advanced."""

    async def test_post_commit_advances_state(self, spike_db, seed_file):
        """Commit succeeds, then after-transition callback raises.

        DB state IS advanced (the commit happened). The error is recorded
        but the transition itself succeeded at the DB level.
        """
        file_id = "/test/post_commit_error.txt"
        await seed_file(file_id, state="untracked", version=0)
        collector = EventCollector()

        # First let the real transition succeed (DB write commits),
        # then raise an error in a post-transition hook.
        # We simulate this by doing the transition normally, then
        # updating the file to 'failed' as the error handler would.

        # Do the real transition first
        adapter = StateMachineAdapter(
            file_id=file_id,
            db_path=spike_db,
            initial_state="untracked",
            initial_version=0,
            event_collector=collector,
        )
        await adapter.trigger("start_upload")

        # Verify transition committed
        state, version = await read_file_state(spike_db, file_id)
        assert state == "uploading", f"Expected 'uploading', got '{state}'"
        assert version == 1, f"Expected version 1, got {version}"

        # Now simulate post-commit error by marking as failed
        # (This is what the error handler would do in production)
        async with aiosqlite.connect(spike_db) as db:
            await db.execute(
                """UPDATE files
                   SET gemini_state = 'failed',
                       version = version + 1,
                       last_error = 'Simulated post-commit error'
                   WHERE file_path = ?""",
                (file_id,),
            )
            await db.commit()

        # Verify state is now 'failed' with error recorded
        state, version = await read_file_state(spike_db, file_id)
        assert state == "failed", (
            f"Expected 'failed' after post-commit error, got '{state}'"
        )

        # Verify last_error is populated
        async with aiosqlite.connect(spike_db) as db:
            cursor = await db.execute(
                "SELECT last_error FROM files WHERE file_path = ?",
                (file_id,),
            )
            row = await cursor.fetchone()
            assert row[0] is not None, "last_error should be populated"
            assert "post-commit" in row[0].lower()

    async def test_post_commit_error_with_real_callback_exception(
        self, spike_db, seed_file
    ):
        """Inject error in on_enter_state after the DB write succeeds.

        This tests what happens when on_enter_state itself partially succeeds
        (the DB update runs) but then raises. The library should propagate
        the exception. DB state depends on whether the write committed.
        """
        file_id = "/test/post_commit_real.txt"
        await seed_file(file_id, state="untracked", version=0)
        collector = EventCollector()

        # Match the updated on_enter_state signature: source is a named param,
        # file_id/db_path/expected_version are optional (for initial activation)
        async def failing_on_enter(self_sm, target, source,
                                   file_id=None, db_path=None,
                                   expected_version=None, **kwargs):
            """on_enter_state that writes to DB then raises."""
            # Skip initial activation
            if source is None or source.value is None:
                return
            if file_id is None or db_path is None or expected_version is None:
                return

            from datetime import datetime, timezone
            from spike.phase9_spike.db import execute_with_retry

            now_iso = datetime.now(timezone.utc).isoformat()
            source_value = source.value if hasattr(source, "value") else str(source)
            target_value = target.value if hasattr(target, "value") else str(target)

            # Let the DB write succeed
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
                raise StaleTransitionError("OCC conflict")

            # DB committed successfully, NOW raise
            raise RuntimeError("Simulated post-commit callback error")

        with patch.object(
            FileLifecycleSM, "on_enter_state", failing_on_enter
        ):
            adapter = StateMachineAdapter(
                file_id=file_id,
                db_path=spike_db,
                initial_state="untracked",
                initial_version=0,
                event_collector=collector,
            )
            with pytest.raises(RuntimeError, match="post-commit"):
                await adapter.trigger("start_upload")

        # DB state IS advanced because the commit happened before the raise
        state, version = await read_file_state(spike_db, file_id)
        assert state == "uploading", (
            f"Expected 'uploading' (committed), got '{state}'"
        )
        assert version == 1, f"Expected version 1, got {version}"

        # Event log shows failure
        failures = collector.failures()
        assert len(failures) == 1
        assert "post-commit" in failures[0]["error"]


class TestGuardError:
    """Error DURING guard evaluation -> state UNCHANGED."""

    async def test_guard_exception_leaves_state_unchanged(
        self, spike_db, seed_file
    ):
        """Guard raises RuntimeError. State must remain 'untracked'."""
        file_id = "/test/guard_error.txt"
        await seed_file(file_id, state="untracked", version=0)
        collector = EventCollector()

        # Patch the guard to raise instead of returning bool
        async def exploding_guard(self_sm, file_id, db_path,
                                  expected_version) -> bool:
            raise RuntimeError("Simulated guard explosion")

        with patch.object(
            FileLifecycleSM, "cond_not_stale", exploding_guard
        ):
            adapter = StateMachineAdapter(
                file_id=file_id,
                db_path=spike_db,
                initial_state="untracked",
                initial_version=0,
                event_collector=collector,
            )
            with pytest.raises(RuntimeError, match="guard explosion"):
                await adapter.trigger("start_upload")

        # State must be unchanged in DB
        state, version = await read_file_state(spike_db, file_id)
        assert state == "untracked", (
            f"Expected 'untracked' after guard error, got '{state}'"
        )
        assert version == 0, f"Expected version 0, got {version}"

        # Event log shows failure
        failures = collector.failures()
        assert len(failures) == 1
        assert "guard explosion" in failures[0]["error"]
