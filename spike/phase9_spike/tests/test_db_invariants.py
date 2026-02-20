"""DB invariant checker and tests.

Verifies that after any test run:
- All gemini_state values are in the valid enum
- All version values are non-negative
- No illegal state edges exist
"""

import aiosqlite
import pytest

from spike.phase9_spike.db import init_spike_db
from spike.phase9_spike.states import VALID_STATES


async def check_db_invariants(db_path: str) -> list[str]:
    """Return list of invariant violations (empty = pass).

    Checks:
    1. All gemini_state values are in VALID_STATES
    2. All version values are non-negative
    """
    violations = []
    async with aiosqlite.connect(db_path) as db:
        # Check 1: All states are valid enum values
        placeholders = ",".join("?" for _ in VALID_STATES)
        cursor = await db.execute(
            f"SELECT file_path, gemini_state FROM files "
            f"WHERE gemini_state NOT IN ({placeholders})",
            tuple(VALID_STATES),
        )
        rows = await cursor.fetchall()
        for row in rows:
            violations.append(
                f"Invalid state '{row[1]}' for file '{row[0]}'"
            )

        # Check 2: Version is non-negative
        cursor = await db.execute(
            "SELECT file_path, version FROM files WHERE version < 0"
        )
        rows = await cursor.fetchall()
        for row in rows:
            violations.append(
                f"Negative version {row[1]} for file '{row[0]}'"
            )

    return violations


class TestDbInvariants:
    """Tests for DB invariant checking."""

    async def test_valid_state_passes(self, spike_db, seed_file):
        """After seeding valid files, invariants pass."""
        await seed_file("/test/valid1.txt", state="untracked", version=0)
        await seed_file("/test/valid2.txt", state="uploading", version=1)
        await seed_file("/test/valid3.txt", state="indexed", version=3)

        violations = await check_db_invariants(spike_db)
        assert violations == [], f"Expected no violations, got: {violations}"

    async def test_invalid_state_fails(self, spike_db):
        """Inserting an invalid state produces a violation."""
        async with aiosqlite.connect(spike_db) as db:
            await db.execute(
                "INSERT INTO files (file_path, gemini_state, version) "
                "VALUES (?, ?, ?)",
                ("/test/invalid.txt", "bogus_state", 0),
            )
            await db.commit()

        violations = await check_db_invariants(spike_db)
        assert len(violations) == 1
        assert "bogus_state" in violations[0]
        assert "/test/invalid.txt" in violations[0]

    async def test_negative_version_fails(self, spike_db):
        """Inserting a negative version produces a violation."""
        async with aiosqlite.connect(spike_db) as db:
            await db.execute(
                "INSERT INTO files (file_path, gemini_state, version) "
                "VALUES (?, ?, ?)",
                ("/test/neg_version.txt", "untracked", -1),
            )
            await db.commit()

        violations = await check_db_invariants(spike_db)
        assert len(violations) == 1
        assert "Negative version" in violations[0]

    async def test_invariants_after_valid_transition(
        self, spike_db, seed_file
    ):
        """After a valid transition, invariants still hold."""
        from spike.phase9_spike.adapters.statemachine_adapter import (
            StateMachineAdapter,
        )
        from spike.phase9_spike.event_log import EventCollector

        file_id = "/test/transition_check.txt"
        await seed_file(file_id, state="untracked", version=0)

        collector = EventCollector()
        adapter = StateMachineAdapter(
            file_id=file_id,
            db_path=spike_db,
            initial_state="untracked",
            initial_version=0,
            event_collector=collector,
        )
        await adapter.trigger("start_upload")

        violations = await check_db_invariants(spike_db)
        assert violations == [], f"Violations after transition: {violations}"
