"""File lifecycle finite state machine for the Gemini upload pipeline.

Each file gets its own FSM instance, initialized at the file's current
gemini_state. Used to validate transition legality before
AsyncUploadStateManager persists the state change.

The FSM is purely a validation tool -- it does NOT perform DB writes or
have on_enter_state callbacks.  The production pattern uses
transition_to_*() methods on AsyncUploadStateManager for DB persistence,
not FSM callbacks.
"""

from __future__ import annotations

from statemachine import State, StateMachine


class FileLifecycleSM(StateMachine):
    """Five-state lifecycle for a file's journey through Gemini upload.

    States:
        untracked  -- File exists in DB but has no Gemini presence.
        uploading  -- File upload API call in flight.
        processing -- Upload complete, import/indexing in progress.
        indexed    -- File is searchable in Gemini store.
        failed     -- An error occurred (from uploading or processing).

    No state has ``final=True`` (Phase 10 finding -- causes
    InvalidDefinition with python-statemachine 2.6.0).
    """

    # 5 states, NO final=True on any state
    untracked = State("untracked", initial=True, value="untracked")
    uploading = State("uploading", value="uploading")
    processing = State("processing", value="processing")
    indexed = State("indexed", value="indexed")
    failed = State("failed", value="failed")

    # 8 transitions
    start_upload = untracked.to(uploading)
    complete_upload = uploading.to(processing)
    complete_processing = processing.to(indexed)
    fail_upload = uploading.to(failed)
    fail_processing = processing.to(failed)
    reset = indexed.to(untracked)
    retry = failed.to(untracked)
    fail_reset = indexed.to(failed)


def create_fsm(current_state: str) -> FileLifecycleSM:
    """Create an FSM instance at the given state.

    Args:
        current_state: One of 'untracked', 'uploading', 'processing',
            'indexed', 'failed'.

    Returns:
        A FileLifecycleSM positioned at *current_state*.
    """
    return FileLifecycleSM(start_value=current_state)
