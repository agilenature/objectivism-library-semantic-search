"""ResetTransitionManager: Txn A -> safe_delete APIs -> Txn B pattern.

Implements the two-transaction optimistic concurrency pattern (GA-6) for
the INDEXED -> UNTRACKED reset transition:

  1. Txn A: Write intent (OCC check, no version increment)
  2. safe_delete_store_document (API call 1)
  3. update_progress(1)
  4. safe_delete_file (API call 2)
  5. update_progress(2)
  6. Txn B: Finalize reset (clears Gemini IDs + intent, increments version)

If the process crashes at any point, the intent columns in DB record
exactly how far the transition got, enabling deterministic recovery
(Plan 10-02).

This manager bypasses StateMachineAdapter for multi-step execution.
The FSM class defines valid transitions but ResetTransitionManager
manages the DB directly with write-ahead intent.
"""

from collections.abc import Callable

from spike.phase9_spike.exceptions import StaleTransitionError
from spike.phase9_spike.integration.scaffold import FileLockManager
from spike.phase10_spike.db import (
    finalize_reset,
    read_file_full,
    update_progress,
    write_intent,
)
from spike.phase10_spike.safe_delete import (
    safe_delete_file,
    safe_delete_store_document,
)


class ResetTransitionManager:
    """Manages the multi-step INDEXED -> UNTRACKED reset transition.

    Uses write-ahead intent columns to track progress through the
    two API calls, enabling crash recovery.

    Args:
        db_path: Path to the spike database.
        delete_store_doc_fn: Async callable to delete a store document.
        delete_file_fn: Async callable to delete a raw file.
    """

    def __init__(
        self,
        db_path: str,
        delete_store_doc_fn: Callable,
        delete_file_fn: Callable,
    ) -> None:
        self._db_path = db_path
        self._delete_store_doc_fn = delete_store_doc_fn
        self._delete_file_fn = delete_file_fn
        self._lock_manager = FileLockManager()

    async def execute_reset(self, file_path: str) -> str:
        """Execute the full INDEXED -> UNTRACKED reset transition.

        Steps:
            1. Acquire per-file lock
            2. Read current state + version
            3. Txn A: Write intent (OCC check)
            4. API call 1: Delete store document
            5. Record progress (api_calls_completed=1)
            6. API call 2: Delete raw file
            7. Record progress (api_calls_completed=2)
            8. Txn B: Finalize reset (clear IDs + intent, increment version)

        Returns:
            "untracked" on success.

        Raises:
            StaleTransitionError: If OCC check fails in Txn A or Txn B.
            Any exception from API calls propagates upward.
        """
        async with self._lock_manager.acquire(file_path):
            # Step 2: Read current state + version
            row = await read_file_full(self._db_path, file_path)
            version = row["version"]

            # Step 3: Txn A -- write intent (no version increment)
            success = await write_intent(self._db_path, file_path, version)
            if not success:
                raise StaleTransitionError(
                    f"OCC conflict in Txn A: file {file_path} "
                    f"(expected version={version})"
                )

            # Step 4: API call 1 -- delete store document
            await safe_delete_store_document(
                self._delete_store_doc_fn, row["gemini_store_doc_id"]
            )

            # Step 5: Record progress (api_calls_completed=1)
            await update_progress(self._db_path, file_path, 1)

            # Step 6: API call 2 -- delete raw file
            await safe_delete_file(
                self._delete_file_fn, row["gemini_file_id"]
            )

            # Step 7: Record progress (api_calls_completed=2)
            await update_progress(self._db_path, file_path, 2)

            # Step 8: Txn B -- finalize reset (increment version)
            success = await finalize_reset(self._db_path, file_path, version)
            if not success:
                raise StaleTransitionError(
                    f"OCC conflict in Txn B: file {file_path} "
                    f"(expected version={version})"
                )

            return "untracked"
