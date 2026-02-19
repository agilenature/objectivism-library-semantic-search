"""Custom Textual Message types for inter-widget communication.

All TUI widgets communicate through the App by posting these messages.
The App handles messages and updates reactive state, which triggers
re-renders in subscribed widgets. No direct widget-to-widget calls.
"""

from __future__ import annotations

from textual.message import Message


class SearchRequested(Message):
    """Fired by search input after debounce delay."""

    def __init__(self, query: str) -> None:
        self.query = query
        super().__init__()


class ResultSelected(Message):
    """Fired when user selects a search result from the results pane."""

    def __init__(self, index: int, citation: object) -> None:
        self.index = index
        self.citation = citation
        super().__init__()


class FileSelected(Message):
    """Fired from nav tree when user selects a file."""

    def __init__(self, file_path: str, filename: str) -> None:
        self.file_path = file_path
        self.filename = filename
        super().__init__()


class FilterChanged(Message):
    """Fired from filter panel when filter criteria change."""

    def __init__(self, filters: object) -> None:
        self.filters = filters
        super().__init__()


class BookmarkToggled(Message):
    """Fired when user toggles a bookmark on a file."""

    def __init__(self, file_path: str, filename: str) -> None:
        self.file_path = file_path
        self.filename = filename
        super().__init__()


class NavigationRequested(Message):
    """Fired when user requests navigation to a category or course."""

    def __init__(
        self,
        category: str | None = None,
        course: str | None = None,
    ) -> None:
        self.category = category
        self.course = course
        super().__init__()
