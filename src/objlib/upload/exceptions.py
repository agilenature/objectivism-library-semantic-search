"""Upload pipeline exception classes."""


class OCCConflictError(Exception):
    """OCC version conflict -- another coroutine modified the file concurrently."""
