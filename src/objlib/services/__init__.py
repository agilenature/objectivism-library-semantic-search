"""Services facade for the Objectivism Library.

Public API boundary for TUI and future clients. Import only from
this package -- never from internal modules (search/, session/,
database.py) directly.
"""

from objlib.services.library import LibraryService
from objlib.services.search import SearchService
from objlib.services.session import SessionService

__all__ = ["SearchService", "LibraryService", "SessionService"]
