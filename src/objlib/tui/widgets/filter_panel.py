"""Filter panel widget for narrowing search and browse results.

Provides Select dropdowns for category, difficulty, and course filters.
Options are populated from the library database on mount. Filter changes
post FilterChanged messages for the App to handle.
"""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Select, Static

from objlib.tui.messages import FilterChanged
from objlib.tui.state import FilterSet


class FilterPanel(Vertical):
    """Collapsible filter panel with category, difficulty, and course dropdowns.

    Options are loaded from LibraryService on mount. Changing any Select
    posts a FilterChanged message with the current FilterSet. The panel
    handles the case where library_service is None (e.g., during tests)
    by leaving options empty.
    """

    DEFAULT_CSS = """
    FilterPanel {
        height: auto;
        max-height: 15;
        padding: 1;
        border-bottom: solid $primary;
        background: $surface;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="filter-panel")

    def compose(self):
        """Yield filter header and Select dropdowns."""
        yield Static("Filters", classes="filter-header")
        yield Select(
            [],
            allow_blank=True,
            prompt="All categories",
            id="filter-category",
        )
        yield Select(
            [
                ("introductory", "introductory"),
                ("intermediate", "intermediate"),
                ("advanced", "advanced"),
            ],
            allow_blank=True,
            prompt="All difficulties",
            id="filter-difficulty",
        )
        yield Select(
            [],
            allow_blank=True,
            prompt="All courses",
            id="filter-course",
        )

    async def on_mount(self) -> None:
        """Populate category and course options from the library database."""
        if self.app.library_service is None:
            return

        try:
            categories = await self.app.library_service.get_categories()
            courses = await self.app.library_service.get_courses()

            self.query_one("#filter-category", Select).set_options(
                [(name, name) for name, _ in categories]
            )
            self.query_one("#filter-course", Select).set_options(
                [(name, name) for name, _ in courses]
            )
        except Exception:
            # Gracefully handle database errors during mount
            pass

    def on_select_changed(self, event: Select.Changed) -> None:
        """Build FilterSet from current Select states and post FilterChanged."""
        cat_val = self.query_one("#filter-category", Select).value
        diff_val = self.query_one("#filter-difficulty", Select).value
        course_val = self.query_one("#filter-course", Select).value

        # Select.NULL is the sentinel for "no selection" in Textual 8.x
        filter_set = FilterSet(
            category=cat_val if cat_val is not Select.NULL else None,
            difficulty=diff_val if diff_val is not Select.NULL else None,
            course=course_val if course_val is not Select.NULL else None,
        )
        self.post_message(FilterChanged(filters=filter_set))

    def reset_filters(self) -> None:
        """Clear all Select widgets and post an empty FilterChanged."""
        self.query_one("#filter-category", Select).value = Select.NULL
        self.query_one("#filter-difficulty", Select).value = Select.NULL
        self.query_one("#filter-course", Select).value = Select.NULL
        self.post_message(FilterChanged(filters=FilterSet()))
