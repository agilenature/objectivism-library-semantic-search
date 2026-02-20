"""Integration scaffold: shows how FSM adapter bridges to AsyncUploadStateManager.

This scaffold demonstrates the Phase 10 integration pattern:
  AsyncUploadStateManager -> FileTransitionManager -> StateMachineAdapter -> DB

Key pattern:
  - FileTransitionManager replaces direct state writes in the upload pipeline
  - FileLockManager (per-file asyncio.Lock) serializes same-file transitions
  - StateMachineAdapter is created EPHEMERAL (per transition, from DB state)
  - AsyncUploadStateManager connection is NOT shared with FSM (separate connections)

This is NOT production code -- it is a proof-of-concept that shows the bridge
pattern for Phase 10 planning. The real implementation will live in src/objlib/.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from spike.phase9_spike.adapters.statemachine_adapter import StateMachineAdapter
from spike.phase9_spike.db import read_file_state
from spike.phase9_spike.event_log import EventCollector
from spike.phase9_spike.exceptions import (
    GuardRejectedError,
    StaleTransitionError,
    TransitionNotAllowedError,
)
from spike.phase9_spike.protocol import FileStateMachineProtocol


class FileLockManager:
    """Per-file asyncio.Lock manager. Serializes transitions on the same file.

    Each file_id gets its own asyncio.Lock. A meta-lock protects the dict
    creation so that two coroutines asking for the same file's lock
    simultaneously don't create two separate Lock objects.

    Usage:
        lock_manager = FileLockManager()
        async with lock_manager.acquire(file_id):
            # Only one coroutine at a time per file_id
            ...
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, file_id: str) -> AsyncIterator[None]:
        """Acquire the per-file lock as an async context manager."""
        async with self._meta_lock:
            if file_id not in self._locks:
                self._locks[file_id] = asyncio.Lock()
            lock = self._locks[file_id]
        async with lock:
            yield


class FileTransitionManager:
    """Bridge between AsyncUploadStateManager and StateMachineAdapter.

    Phase 10 will replace direct state writes in EnrichedUploadOrchestrator
    with calls to FileTransitionManager.trigger_transition().

    The flow:
        1. Acquire per-file lock (FileLockManager)
        2. Read current state and version from DB
        3. Create ephemeral StateMachineAdapter from DB state
        4. Trigger the transition (adapter validates + writes to DB)
        5. Read new state from DB (DB is authoritative)
        6. Return new state

    Usage:
        async with AsyncUploadStateManager(db_path) as state:
            fsm_manager = FileTransitionManager(db_path)
            new_state = await fsm_manager.trigger_transition(
                file_path, "start_upload"
            )
            # FSM handled: read state, validate transition, write new state
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock_manager = FileLockManager()

    async def trigger_transition(
        self,
        file_path: str,
        event: str,
        event_collector: EventCollector | None = None,
    ) -> str:
        """Trigger FSM transition for file. Returns new state.

        Acquires per-file lock, reads state from DB, creates ephemeral adapter,
        triggers transition, returns new state.

        Args:
            file_path: The file to transition.
            event: The event name (e.g., "start_upload").
            event_collector: Optional event collector for logging.

        Returns:
            The new state string after transition.

        Raises:
            StaleTransitionError: OCC version conflict.
            GuardRejectedError: Guard returned False.
            TransitionNotAllowedError: Invalid event for current state.
            ValueError: File not found in DB.
        """
        async with self._lock_manager.acquire(file_path):
            # Read current state from DB (DB is sole source of truth)
            current_state, current_version = await read_file_state(
                self.db_path, file_path
            )

            # Create ephemeral adapter from DB state
            adapter: FileStateMachineProtocol = StateMachineAdapter(
                file_id=file_path,
                db_path=self.db_path,
                initial_state=current_state,
                initial_version=current_version,
                event_collector=event_collector,
            )

            # Trigger transition (adapter validates + writes to DB)
            await adapter.trigger(event)

            # Return new state (read from DB again -- DB is authoritative)
            new_state, _ = await read_file_state(self.db_path, file_path)
            return new_state

    async def get_file_state(self, file_path: str) -> str:
        """Read current file state from DB.

        Args:
            file_path: The file to query.

        Returns:
            The current state string.

        Raises:
            ValueError: File not found in DB.
        """
        state, _ = await read_file_state(self.db_path, file_path)
        return state
