"""Exception types for FSM transition failures."""


class StaleTransitionError(Exception):
    """OCC version conflict -- another coroutine modified the file concurrently."""
    pass


class GuardRejectedError(Exception):
    """Guard condition returned False -- transition not permitted."""
    pass


class TransitionNotAllowedError(Exception):
    """Event is invalid for the current state."""
    pass
