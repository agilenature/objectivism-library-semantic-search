"""Library browsing service facade wrapping Database internals.

Provides async methods for browsing, filtering, and viewing library
content without Gemini API calls. All SQLite operations are wrapped
in asyncio.to_thread() with Database connections opened and closed
within the sync function.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class LibraryService:
    """Async facade for library browsing and filtering.

    Wraps Database methods for categories, courses, files, and
    metadata filtering. No Gemini API calls -- purely local SQLite.

    Usage::

        svc = LibraryService("data/library.db")
        categories = await svc.get_categories()
        files = await svc.filter_files(["category:course", "year:2024"])
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def get_categories(self) -> list[tuple[str, int]]:
        """Get all categories with file counts.

        Returns:
            List of (category_name, count) tuples, ordered by count descending.
        """

        def _query() -> list[tuple[str, int]]:
            from objlib.database import Database

            with Database(self._db_path) as db:
                return db.get_categories_with_counts()

        return await asyncio.to_thread(_query)

    async def get_courses(self) -> list[tuple[str, int]]:
        """Get all courses with file counts.

        Returns:
            List of (course_name, count) tuples, ordered by course name.
        """

        def _query() -> list[tuple[str, int]]:
            from objlib.database import Database

            with Database(self._db_path) as db:
                return db.get_courses_with_counts()

        return await asyncio.to_thread(_query)

    async def get_files_by_course(
        self, course: str, year: str | None = None
    ) -> list[dict]:
        """Get files within a specific course.

        Args:
            course: Course name to filter by.
            year: Optional year string to further filter results.

        Returns:
            List of dicts with 'filename', 'file_path', 'metadata' keys.
        """

        def _query() -> list[dict]:
            from objlib.database import Database

            with Database(self._db_path) as db:
                return db.get_files_by_course(course, year)

        return await asyncio.to_thread(_query)

    async def get_items_by_category(self, category: str) -> list[dict]:
        """Get files within a non-course category.

        Args:
            category: Category name to filter by (e.g., 'motm', 'book').

        Returns:
            List of dicts with 'filename', 'file_path', 'metadata' keys.
        """

        def _query() -> list[dict]:
            from objlib.database import Database

            with Database(self._db_path) as db:
                return db.get_items_by_category(category)

        return await asyncio.to_thread(_query)

    async def filter_files(
        self, filters: list[str], limit: int = 50
    ) -> list[dict]:
        """Filter files by metadata field:value pairs.

        Args:
            filters: List of "field:value" strings (e.g., "category:course",
                     "year:>=2023"). Supports =, >, >=, <, <= operators.
            limit: Maximum results to return.

        Returns:
            List of dicts with 'filename', 'file_path', 'metadata' keys.
        """

        def _query() -> list[dict]:
            from objlib.database import Database

            # Parse "field:value" strings into dict format
            filter_dict: dict[str, str] = {}
            for f in filters:
                key, _, value = f.partition(":")
                if key and value:
                    filter_dict[key] = value

            with Database(self._db_path) as db:
                return db.filter_files_by_metadata(filter_dict, limit)

        return await asyncio.to_thread(_query)

    async def get_file_content(self, file_path: str) -> str | None:
        """Read file content from disk.

        Args:
            file_path: Path to the file on disk.

        Returns:
            File content as string, or None on FileNotFoundError
            or PermissionError.
        """

        def _read() -> str | None:
            try:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    return f.read()
            except (FileNotFoundError, PermissionError):
                return None

        return await asyncio.to_thread(_read)

    async def get_file_count(self) -> int:
        """Get total count of files in the library.

        Returns:
            Integer count of all file records.
        """

        def _query() -> int:
            from objlib.database import Database

            with Database(self._db_path) as db:
                return db.get_file_count()

        return await asyncio.to_thread(_query)
