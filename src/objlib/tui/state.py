"""TUI state dataclasses for filter management and bookmarks."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FilterSet:
    """Active filter criteria for search results.

    Converts non-None fields to CLI-style "field:value" filter strings
    for compatibility with the existing search pipeline.
    """

    category: str | None = None
    course: str | None = None
    difficulty: str | None = None
    year_min: int | None = None
    year_max: int | None = None

    def to_filter_strings(self) -> list[str]:
        """Convert non-None fields to CLI 'field:value' format strings."""
        filters: list[str] = []
        if self.category is not None:
            filters.append(f"category:{self.category}")
        if self.course is not None:
            filters.append(f"course:{self.course}")
        if self.difficulty is not None:
            filters.append(f"difficulty:{self.difficulty}")
        if self.year_min is not None:
            filters.append(f"year_min:{self.year_min}")
        if self.year_max is not None:
            filters.append(f"year_max:{self.year_max}")
        return filters

    def is_empty(self) -> bool:
        """Return True if all filter fields are None."""
        return (
            self.category is None
            and self.course is None
            and self.difficulty is None
            and self.year_min is None
            and self.year_max is None
        )


@dataclass
class Bookmark:
    """A bookmarked library file for quick access."""

    file_path: str
    filename: str
    note: str = ""
