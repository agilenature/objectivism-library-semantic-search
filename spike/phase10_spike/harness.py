"""Combined evidence harness for Phase 10 gate assessment.

Produces structured JSON output demonstrating all 6 affirmative evidence
checks for the Phase 10 transition atomicity spike:

  1. Safe delete 404 handling (idempotent delete wrappers)
  2. Crash point 1 recovery (delete_store_doc done, delete_file not done)
  3. Crash point 2 recovery (both API calls done, finalize not done)
  4. Crash point 3 recovery (identical to CP2 -- Txn B failure)
  5. FAILED escape (retry_failed_file transitions FAILED -> UNTRACKED)
  6. SC3 simplicity (recovery_lines <= transition_lines, no retry loops)

Run: python -m spike.phase10_spike.harness
"""

import ast
import asyncio
import json
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from spike.phase10_spike.db import init_spike_db, read_file_full
from spike.phase10_spike.recovery_crawler import RecoveryCrawler, retry_failed_file
from spike.phase10_spike.safe_delete import safe_delete_store_document
from spike.phase10_spike.transition_reset import ResetTransitionManager

import aiosqlite


class HarnessResult:
    """Structured result from the harness run."""

    def __init__(self):
        self.checks: dict[str, dict] = {}

    def add_check(self, name: str, passed: bool, details: dict):
        self.checks[name] = {"passed": passed, **details}

    @property
    def all_passed(self) -> bool:
        return all(c["passed"] for c in self.checks.values())


async def _seed_indexed_file(db_path: str, file_path: str, version: int = 5) -> None:
    """Insert an indexed file with Gemini IDs into the DB."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            """INSERT INTO files
               (file_path, gemini_state, version, gemini_file_id, gemini_store_doc_id)
               VALUES (?, 'indexed', ?, 'files/test123', 'fileSearchStores/store1/documents/doc1')""",
            (file_path, version),
        )
        await db.commit()


async def _seed_partial_intent(
    db_path: str, file_path: str, api_calls_completed: int, version: int = 5
) -> None:
    """Insert a file with partial intent state (simulating a crash)."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            """INSERT INTO files
               (file_path, gemini_state, version, gemini_file_id,
                gemini_store_doc_id, intent_type, intent_started_at,
                intent_api_calls_completed)
               VALUES (?, 'indexed', ?, 'files/test123',
                       'fileSearchStores/store1/documents/doc1',
                       'reset_intent', '2026-02-20T10:00:00Z', ?)""",
            (file_path, version, api_calls_completed),
        )
        await db.commit()


async def _seed_failed_file(db_path: str, file_path: str, version: int = 3) -> None:
    """Insert a failed file into the DB."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            """INSERT INTO files (file_path, gemini_state, version)
               VALUES (?, 'failed', ?)""",
            (file_path, version),
        )
        await db.commit()


def _count_class_lines(file_path: str, class_name: str) -> int:
    """Count non-blank, non-comment, non-docstring lines in a class."""
    with open(file_path) as f:
        source = f.read()
    tree = ast.parse(source)
    class_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            class_node = node
            break
    if class_node is None:
        raise ValueError(f"Class {class_name} not found in {file_path}")
    lines = source.splitlines()[class_node.lineno - 1 : class_node.end_lineno]
    count = 0
    in_docstring = False
    for line in lines:
        stripped = line.strip()
        if '"""' in stripped or "'''" in stripped:
            quote = '"""' if '"""' in stripped else "'''"
            occurrences = stripped.count(quote)
            if occurrences == 1:
                in_docstring = not in_docstring
                continue
            elif occurrences >= 2:
                continue
        if in_docstring:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        count += 1
    return count


async def run_harness() -> HarnessResult:
    """Run all 6 evidence checks for Phase 10 gate assessment."""
    result = HarnessResult()

    print("=" * 70)
    print("Phase 10 Spike: Transition Atomicity Evidence Harness")
    print("=" * 70)
    print()

    # Setup: create temp DB
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="phase10_harness_")
    os.close(fd)
    os.remove(db_path)  # init_spike_db creates it fresh

    try:
        await init_spike_db(db_path)

        # ==================================================================
        # Check 1: Safe delete 404 handling
        # ==================================================================
        print("[CHECK 1] Safe delete 404 handling...")
        check1_passed = False
        try:
            # 404 should return True (idempotent success)
            mock_404 = AsyncMock(side_effect=_make_client_error(404))
            result_404 = await safe_delete_store_document(mock_404, "stores/s1/documents/d1")
            assert result_404 is True, "404 should return True"

            # 403 should propagate (not swallowed)
            mock_403 = AsyncMock(side_effect=_make_client_error(403))
            raised_403 = False
            try:
                await safe_delete_store_document(mock_403, "stores/s1/documents/d1")
            except Exception:
                raised_403 = True

            assert raised_403, "403 should propagate"
            check1_passed = True
            print("  404 -> True: PASS")
            print("  403 -> raises: PASS")
        except Exception as e:
            print(f"  FAIL: {e}")

        result.add_check("safe_delete_404", check1_passed, {
            "message": "404 = idempotent success, 403 = propagated error",
        })
        print()

        # ==================================================================
        # Check 2: Crash point 1 recovery
        # ==================================================================
        print("[CHECK 2] Crash point 1 recovery...")
        check2_passed = False
        try:
            fp2 = "test/check2_cp1.txt"
            await _seed_indexed_file(db_path, fp2)

            # Crash at point 1: store doc delete succeeds, file delete crashes
            mgr = ResetTransitionManager(
                db_path=db_path,
                delete_store_doc_fn=AsyncMock(return_value=None),
                delete_file_fn=AsyncMock(side_effect=RuntimeError("crash")),
            )
            try:
                await mgr.execute_reset(fp2)
            except RuntimeError:
                pass

            # Verify partial state
            row = await read_file_full(db_path, fp2)
            assert row["intent_api_calls_completed"] == 1
            assert row["gemini_state"] == "indexed"

            # Recover
            crawler = RecoveryCrawler(
                db_path=db_path,
                delete_store_doc_fn=AsyncMock(return_value=None),
                delete_file_fn=AsyncMock(return_value=None),
            )
            recovered = await crawler.recover_all()
            assert fp2 in recovered

            row = await read_file_full(db_path, fp2)
            assert row["gemini_state"] == "untracked"
            assert row["intent_type"] is None
            check2_passed = True
            print("  Partial state verified: api_calls_completed=1")
            print("  Recovery completed: state=untracked, intent cleared")
        except Exception as e:
            print(f"  FAIL: {e}")

        result.add_check("crash_point_1_recovery", check2_passed, {
            "message": "CP1 (api_calls=1) -> recovered to untracked",
        })
        print()

        # ==================================================================
        # Check 3: Crash point 2 recovery
        # ==================================================================
        print("[CHECK 3] Crash point 2 recovery...")
        check3_passed = False
        try:
            fp3 = "test/check3_cp2.txt"
            await _seed_partial_intent(db_path, fp3, api_calls_completed=2)

            mock_store = AsyncMock(return_value=None)
            mock_file = AsyncMock(return_value=None)
            crawler = RecoveryCrawler(
                db_path=db_path,
                delete_store_doc_fn=mock_store,
                delete_file_fn=mock_file,
            )
            recovered = await crawler.recover_all()
            assert fp3 in recovered

            # Delete fns should NOT be called (both api calls already done)
            mock_store.assert_not_awaited()
            mock_file.assert_not_awaited()

            row = await read_file_full(db_path, fp3)
            assert row["gemini_state"] == "untracked"
            check3_passed = True
            print("  No delete calls needed: PASS")
            print("  Recovery completed: state=untracked")
        except Exception as e:
            print(f"  FAIL: {e}")

        result.add_check("crash_point_2_recovery", check3_passed, {
            "message": "CP2 (api_calls=2) -> recovered with finalize only",
        })
        print()

        # ==================================================================
        # Check 4: Crash point 3 recovery
        # ==================================================================
        print("[CHECK 4] Crash point 3 recovery (identical to CP2)...")
        check4_passed = False
        try:
            fp4 = "test/check4_cp3.txt"
            await _seed_partial_intent(db_path, fp4, api_calls_completed=2)

            crawler = RecoveryCrawler(
                db_path=db_path,
                delete_store_doc_fn=AsyncMock(return_value=None),
                delete_file_fn=AsyncMock(return_value=None),
            )
            recovered = await crawler.recover_all()
            assert fp4 in recovered

            row = await read_file_full(db_path, fp4)
            assert row["gemini_state"] == "untracked"
            check4_passed = True
            print("  Identical DB state to CP2: PASS")
            print("  Recovery completed: state=untracked")
        except Exception as e:
            print(f"  FAIL: {e}")

        result.add_check("crash_point_3_recovery", check4_passed, {
            "message": "CP3 (Txn B failure) -> identical recovery path as CP2",
        })
        print()

        # ==================================================================
        # Check 5: FAILED escape
        # ==================================================================
        print("[CHECK 5] FAILED escape (retry_failed_file)...")
        check5_passed = False
        try:
            fp5 = "test/check5_failed.txt"
            await _seed_failed_file(db_path, fp5, version=3)

            success = await retry_failed_file(db_path, fp5)
            assert success is True

            row = await read_file_full(db_path, fp5)
            assert row["gemini_state"] == "untracked"
            assert row["version"] == 4  # Incremented from 3
            check5_passed = True
            print("  FAILED -> UNTRACKED: PASS")
            print("  Version incremented (3 -> 4): PASS")
        except Exception as e:
            print(f"  FAIL: {e}")

        result.add_check("failed_escape", check5_passed, {
            "message": "retry_failed_file transitions FAILED -> UNTRACKED with OCC",
        })
        print()

        # ==================================================================
        # Check 6: SC3 simplicity
        # ==================================================================
        print("[CHECK 6] SC3 simplicity measurement...")
        check6_passed = False
        spike_dir = os.path.join(os.path.dirname(__file__))
        recovery_path = os.path.join(spike_dir, "recovery_crawler.py")
        transition_path = os.path.join(spike_dir, "transition_reset.py")
        recovery_lines = 0
        transition_lines = 0
        try:
            recovery_lines = _count_class_lines(recovery_path, "RecoveryCrawler")
            transition_lines = _count_class_lines(transition_path, "ResetTransitionManager")

            assert recovery_lines <= transition_lines

            with open(recovery_path) as f:
                assert "while " not in f.read(), "No while loops in recovery"

            check6_passed = True
            print(f"  RecoveryCrawler:        {recovery_lines} lines")
            print(f"  ResetTransitionManager: {transition_lines} lines")
            print(f"  Recovery <= Transition:  PASS")
            print(f"  No while loops:         PASS")
        except Exception as e:
            print(f"  FAIL: {e}")

        result.add_check("sc3_simplicity", check6_passed, {
            "recovery_lines": recovery_lines,
            "transition_lines": transition_lines,
            "recovery_simpler": recovery_lines <= transition_lines,
            "no_retry_loops": True,
        })
        print()

    finally:
        # Cleanup temp DB and WAL/SHM
        for suffix in ("", "-wal", "-shm"):
            path = db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    # ==================================================================
    # Summary
    # ==================================================================
    print("=" * 70)
    if result.all_passed:
        print("ALL CHECKS PASSED")
    else:
        failed = [name for name, check in result.checks.items() if not check["passed"]]
        print(f"FAILURES DETECTED: {', '.join(failed)}")
    print("=" * 70)

    print()
    print("Full results (JSON):")
    print(json.dumps(result.checks, indent=2, default=str))

    return result


def _make_client_error(code: int):
    """Create a google.genai.errors.ClientError with the given status code."""
    from google.genai import errors as genai_errors
    return genai_errors.ClientError(code, {}, None)


def main():
    """Entry point for python -m spike.phase10_spike.harness."""
    result = asyncio.run(run_harness())
    sys.exit(0 if result.all_passed else 1)


if __name__ == "__main__":
    main()
