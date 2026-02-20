"""BINARY PASS/FAIL test for python-statemachine async guards.

This is THE critical test that determines whether we proceed with
python-statemachine or pivot to hand-rolled. It runs FIRST.

If test_async_guard_is_awaited FAILS: the library does not await async guards,
and we must pivot to hand-rolled. The test prints a clear PIVOT REQUIRED message.
"""

import aiosqlite
import pytest
from statemachine import State, StateMachine

from spike.phase9_spike.db import init_spike_db


# ---------------------------------------------------------------------------
# Minimal python-statemachine subclass with one async guard
# ---------------------------------------------------------------------------

class MinimalAsyncGuardSM(StateMachine):
    """Minimal SM to test if the library awaits an async guard."""

    untracked = State("untracked", initial=True, value="untracked")
    uploading = State("uploading", value="uploading")

    start_upload = untracked.to(uploading, cond="cond_not_stale")

    async def cond_not_stale(
        self, file_id: str, db_path: str, expected_version: int
    ) -> bool:
        """Async guard: queries DB to check OCC version."""
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT version FROM files WHERE file_path = ?", (file_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return False
            return row[0] == expected_version


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAsyncGuardBinary:
    """Binary pass/fail tests for python-statemachine async guard support."""

    @pytest.fixture
    async def guard_db(self, tmp_path):
        """Create a DB with one seeded file for guard tests."""
        db_path = str(tmp_path / "guard_test.db")
        await init_spike_db(db_path)
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO files (file_path, gemini_state, version) "
                "VALUES (?, ?, ?)",
                ("/test/guard_file.txt", "untracked", 0),
            )
            await db.commit()
        return db_path

    async def test_async_guard_is_awaited(self, guard_db):
        """CRITICAL: Prove python-statemachine awaits async guard.

        If this fails, PIVOT to hand-rolled immediately.
        """
        db_path = guard_db
        file_id = "/test/guard_file.txt"

        try:
            sm = MinimalAsyncGuardSM()
            await sm.activate_initial_state()
            assert sm.current_state_value == "untracked"

            # Trigger with correct version -- guard should return True
            await sm.send(
                "start_upload",
                file_id=file_id,
                db_path=db_path,
                expected_version=0,
            )

            # If we get here, the library awaited the async guard
            assert sm.current_state_value == "uploading", (
                f"Expected 'uploading', got '{sm.current_state_value}'"
            )

        except (RuntimeError, TypeError) as e:
            # Library did NOT await the async guard
            print(
                "\n" + "=" * 70 + "\n"
                "PIVOT REQUIRED: python-statemachine does not await async guards.\n"
                f"Error: {e}\n"
                "Switching to hand-rolled adapter.\n"
                + "=" * 70
            )
            pytest.fail(
                f"python-statemachine async guard not awaited: {e}"
            )

    async def test_async_guard_rejects(self, guard_db):
        """Guard returns False (wrong version) -- transition must be rejected."""
        db_path = guard_db
        file_id = "/test/guard_file.txt"

        sm = MinimalAsyncGuardSM()
        await sm.activate_initial_state()
        assert sm.current_state_value == "untracked"

        # Trigger with wrong version -- guard should return False
        # python-statemachine raises TransitionNotAllowed when cond fails
        from statemachine.exceptions import TransitionNotAllowed

        with pytest.raises(TransitionNotAllowed):
            await sm.send(
                "start_upload",
                file_id=file_id,
                db_path=db_path,
                expected_version=999,  # Wrong version
            )

        # State should remain unchanged
        assert sm.current_state_value == "untracked", (
            f"Expected 'untracked' after guard rejection, "
            f"got '{sm.current_state_value}'"
        )

    async def test_start_value_string(self):
        """Test start_value with string value (LOW confidence from RESEARCH.md).

        Verifies that creating an FSM with start_value='uploading' works
        when states are defined with value='uploading'.
        """
        sm = MinimalAsyncGuardSM(start_value="uploading")
        await sm.activate_initial_state()
        assert sm.current_state_value == "uploading", (
            f"Expected 'uploading' from start_value, "
            f"got '{sm.current_state_value}'"
        )
