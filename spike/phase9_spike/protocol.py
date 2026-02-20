"""FileStateMachineProtocol -- interface-first design for FSM adapter swap.

Defined BEFORE any library trial so that a pivot from python-statemachine
to hand-rolled does not require rewriting test harness or caller code.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class FileStateMachineProtocol(Protocol):
    """Interface for file lifecycle state machines.

    All test harness code is written against this Protocol.
    Both the python-statemachine adapter and the hand-rolled
    fallback must satisfy this interface.
    """

    @property
    def current_state(self) -> str:
        """Current FSM state as a string ('untracked', 'uploading', etc.)."""
        ...

    async def trigger(self, event: str, **kwargs) -> None:
        """Trigger a state transition.

        Args:
            event: Transition event name (e.g., 'start_upload')
            **kwargs: Passed through to guards and callbacks

        Raises:
            StaleTransitionError: OCC version conflict
            GuardRejectedError: Guard returned False
            TransitionNotAllowedError: Invalid event for current state
        """
        ...

    async def can_trigger(self, event: str, **kwargs) -> bool:
        """Check if the event can be triggered without side effects."""
        ...
