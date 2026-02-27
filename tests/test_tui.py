"""User Acceptance Tests for the Objectivism Library TUI.

Covers all current TUI functionality using Textual's headless testing API
(App.run_test / Pilot) with mock services for database isolation.

asyncio_mode = "auto" in pyproject.toml means async test functions are
automatically discovered and run without explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from objlib.models import Citation, SearchResult
from objlib.tui.app import ObjlibApp
from objlib.tui.messages import (
    FileSelected,
    FilterChanged,
    NavigationRequested,
    ResultSelected,
    SearchRequested,
)
from objlib.tui.state import Bookmark, FilterSet
from objlib.tui.widgets import FilterPanel, NavTree, PreviewPane, ResultsList, SearchBar
from objlib.tui.widgets.results import ResultItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_citations() -> list[Citation]:
    """Two test Citation objects with full metadata for result testing."""
    return [
        Citation(
            index=1,
            title="OPAR - Lesson 01.txt",
            uri=None,
            text="Philosophy is the science of existence and consciousness.",
            document_name=None,
            confidence=0.9,
            file_path="/library/OPAR - Lesson 01.txt",
            metadata={"course": "OPAR", "year": 2020, "difficulty": "intermediate"},
        ),
        Citation(
            index=2,
            title="Ethics - Lesson 01.txt",
            uri=None,
            text="Rational egoism holds that self-interest is the proper motive.",
            document_name=None,
            confidence=0.8,
            file_path="/library/Ethics - Lesson 01.txt",
            metadata={"course": "Ethics", "difficulty": "advanced"},
        ),
    ]


@pytest.fixture
def mock_library_service() -> AsyncMock:
    """Mock LibraryService with realistic return values for all methods."""
    svc = AsyncMock()
    svc.get_categories.return_value = [("course", 100), ("book", 50)]
    svc.get_courses.return_value = [("OPAR", 20), ("Ethics", 15)]
    svc.get_files_by_course.return_value = [
        {"filename": "OPAR - Lesson 01.txt", "file_path": "/library/OPAR - Lesson 01.txt"}
    ]
    svc.get_items_by_category.return_value = [
        {"filename": "Test.txt", "file_path": "/library/Test.txt"}
    ]
    svc.get_file_content.return_value = "This is the full document content."
    svc.get_file_count.return_value = 1884
    return svc


@pytest.fixture
def mock_search_service(sample_citations) -> AsyncMock:
    """Mock SearchService returning predictable citations on every search."""
    svc = AsyncMock()
    svc.search.return_value = SearchResult(
        response_text="Test search response",
        citations=sample_citations,
        query="test query",
        metadata_filter=None,
    )
    svc.synthesize.return_value = None
    return svc


@pytest.fixture
def mock_session_service() -> AsyncMock:
    """Mock SessionService with empty session store by default."""
    svc = AsyncMock()
    svc.create_session.return_value = "session-uuid-12345678"
    svc.list_sessions.return_value = []
    svc.get_events.return_value = []
    svc.add_event.return_value = None
    return svc


def make_app(
    search_service=None,
    library_service=None,
    session_service=None,
) -> ObjlibApp:
    """Factory for ObjlibApp with optional mock services."""
    return ObjlibApp(
        search_service=search_service,
        library_service=library_service,
        session_service=session_service,
    )


# ---------------------------------------------------------------------------
# FilterSet Unit Tests (pure Python, no Textual context needed)
# ---------------------------------------------------------------------------


class TestFilterSet:
    def test_default_is_empty(self):
        assert FilterSet().is_empty() is True

    def test_not_empty_when_category_set(self):
        assert FilterSet(category="course").is_empty() is False

    def test_not_empty_when_difficulty_set(self):
        assert FilterSet(difficulty="advanced").is_empty() is False

    def test_not_empty_when_course_set(self):
        assert FilterSet(course="OPAR").is_empty() is False

    def test_not_empty_when_year_min_set(self):
        assert FilterSet(year_min=2020).is_empty() is False

    def test_not_empty_when_year_max_set(self):
        assert FilterSet(year_max=2025).is_empty() is False

    def test_to_filter_strings_empty_produces_empty_list(self):
        assert FilterSet().to_filter_strings() == []

    def test_to_filter_strings_category_only(self):
        strings = FilterSet(category="course").to_filter_strings()
        assert strings == ["category:course"]

    def test_to_filter_strings_all_fields(self):
        fs = FilterSet(
            category="course",
            course="OPAR",
            difficulty="advanced",
            year_min=2020,
            year_max=2024,
        )
        assert fs.to_filter_strings() == [
            "category:course",
            "course:OPAR",
            "difficulty:advanced",
            "year_min:2020",
            "year_max:2024",
        ]

    def test_to_filter_strings_partial_fields(self):
        strings = FilterSet(difficulty="intermediate").to_filter_strings()
        assert strings == ["difficulty:intermediate"]

    def test_to_filter_strings_year_range_only(self):
        strings = FilterSet(year_min=2019, year_max=2023).to_filter_strings()
        assert "year_min:2019" in strings
        assert "year_max:2023" in strings
        assert len(strings) == 2


# ---------------------------------------------------------------------------
# Bookmark Unit Tests
# ---------------------------------------------------------------------------


class TestBookmark:
    def test_construction_with_required_fields(self):
        b = Bookmark(file_path="/path/file.txt", filename="file.txt")
        assert b.file_path == "/path/file.txt"
        assert b.filename == "file.txt"
        assert b.note == ""

    def test_construction_with_note(self):
        b = Bookmark(file_path="/path/file.txt", filename="file.txt", note="Key lecture")
        assert b.note == "Key lecture"

    def test_two_bookmarks_are_equal_when_same(self):
        b1 = Bookmark(file_path="/path/file.txt", filename="file.txt")
        b2 = Bookmark(file_path="/path/file.txt", filename="file.txt")
        assert b1 == b2

    def test_two_bookmarks_differ_by_file_path(self):
        b1 = Bookmark(file_path="/path/a.txt", filename="a.txt")
        b2 = Bookmark(file_path="/path/b.txt", filename="b.txt")
        assert b1 != b2


# ---------------------------------------------------------------------------
# App Initialization Tests
# ---------------------------------------------------------------------------


async def test_app_mounts_without_services():
    """App starts cleanly with no services — useful for offline/test mode."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.query_one(SearchBar) is not None
        assert app.query_one(NavTree) is not None
        assert app.query_one(ResultsList) is not None
        assert app.query_one(PreviewPane) is not None
        assert app.query_one(FilterPanel) is not None


async def test_app_mounts_with_services(mock_library_service):
    """App populates nav tree and filter panel on mount when library service present."""
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        mock_library_service.get_categories.assert_called()


async def test_app_reactive_defaults():
    """Reactive properties start at correct default values."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.query == ""
        assert app.results == []
        assert app.selected_index is None
        assert app.is_searching is False
        assert app.active_session_id is None
        assert app.bookmarks == []
        assert app.active_filters.is_empty() is True


async def test_app_title_and_subtitle():
    """App has correct title and subtitle."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.TITLE == "Objectivism Library"
        assert app.SUB_TITLE == "Semantic Search & Browse"


async def test_app_bindings_count():
    """App defines exactly 8 key bindings."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        assert len(app.BINDINGS) == 8


async def test_app_includes_objlib_commands_provider():
    """App registers ObjlibCommands as a command palette provider."""
    from objlib.tui.providers import ObjlibCommands

    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        assert ObjlibCommands in app.COMMANDS


async def test_preview_shows_placeholder_on_mount():
    """Preview pane shows placeholder message on startup (no document loaded)."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        assert preview._current_content is None


# ---------------------------------------------------------------------------
# Search Flow Tests
# ---------------------------------------------------------------------------


async def test_empty_search_clears_results(mock_search_service):
    """Empty query via input clears results, resets selected_index.

    Updated for RxPY pipeline (plan 17-04): replaced post_message(SearchRequested)
    with input_subject.on_next("") which triggers the empty-query clear subscription.
    Requires search_service so the RxPY pipeline (including clear subscription) is wired.
    """
    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.results = [Citation(1, "Test", None, "text", None, 0.5)]
        app.query = "previous query"
        app.selected_index = 0

        # Drive empty query through the RxPY pipeline's clear subscription
        search_bar = app.query_one(SearchBar)
        search_bar.input_subject.on_next("")
        await pilot.pause(0.2)

        assert app.query == ""
        assert app.results == []
        assert app.selected_index is None


async def test_search_triggers_service_call(mock_search_service, mock_library_service):
    """Enter-submitted query calls search_service.search().

    Updated for RxPY pipeline (plan 17-04): replaced post_message(SearchRequested)
    with _enter_subject.on_next() which fires search through the RxPY pipeline.
    """
    app = make_app(search_service=mock_search_service, library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar._enter_subject.on_next("virtue")
        await pilot.pause(0.5)

        mock_search_service.search.assert_called_once()
        assert mock_search_service.search.call_args[0][0] == "virtue"


async def test_search_results_populate_list(mock_search_service, mock_library_service, sample_citations):
    """After search completes, ResultsList contains one ResultItem per citation.

    Updated for RxPY pipeline (plan 17-04): replaced post_message(SearchRequested)
    with _enter_subject.on_next() which fires search through the RxPY pipeline.
    """
    app = make_app(search_service=mock_search_service, library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar._enter_subject.on_next("consciousness")
        await pilot.pause(0.5)

        assert len(app.results) == len(sample_citations)
        items = list(app.query_one(ResultsList).query(ResultItem))
        assert len(items) == len(sample_citations)


async def test_search_updates_reactive_query(mock_search_service, mock_library_service):
    """Search via Enter updates app.query reactive property.

    Updated for RxPY pipeline (plan 17-04): replaced post_message(SearchRequested)
    with _enter_subject.on_next() which fires search through the RxPY pipeline.
    """
    app = make_app(search_service=mock_search_service, library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar._enter_subject.on_next("epistemology")
        await pilot.pause(0.5)

        assert app.query == "epistemology"


async def test_search_with_active_filters_passes_filter_strings(
    mock_search_service, mock_library_service
):
    """Search with active filters forwards filter strings to the service.

    Updated for RxPY pipeline (plan 17-04): replaced post_message(SearchRequested)
    with _enter_subject.on_next(). Set filters via _filter_subject so the
    combine_latest pipeline picks them up.
    """
    app = make_app(search_service=mock_search_service, library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        # Feed filter through the BehaviorSubject so combine_latest sees it
        app._filter_subject.on_next(FilterSet(difficulty="advanced"))
        search_bar = app.query_one(SearchBar)
        search_bar._enter_subject.on_next("ethics")
        await pilot.pause(0.5)

        call_kwargs = mock_search_service.search.call_args[1]
        assert call_kwargs.get("filters") is not None
        assert "difficulty:advanced" in call_kwargs["filters"]


async def test_search_with_empty_filters_passes_no_filters(
    mock_search_service, mock_library_service
):
    """Search with no active filters passes filters=None to service.

    Updated for RxPY pipeline (plan 17-04): replaced post_message(SearchRequested)
    with _enter_subject.on_next() which fires search through the RxPY pipeline.
    """
    app = make_app(search_service=mock_search_service, library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar._enter_subject.on_next("metaphysics")
        await pilot.pause(0.5)

        call_kwargs = mock_search_service.search.call_args[1]
        assert call_kwargs.get("filters") is None


async def test_search_without_service_does_nothing():
    """SearchRequested with no search_service silently does nothing."""
    app = make_app(search_service=None)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(SearchRequested(query="test"))
        await pilot.pause(0.3)
        assert app.results == []


async def test_search_logs_to_active_session(
    mock_search_service, mock_library_service, mock_session_service
):
    """An active session receives a 'search' event after each search.

    Updated for RxPY pipeline (plan 17-04): replaced post_message(SearchRequested)
    with _enter_subject.on_next() which fires search through the RxPY pipeline.
    """
    app = make_app(
        search_service=mock_search_service,
        library_service=mock_library_service,
        session_service=mock_session_service,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.active_session_id = "session-uuid-12345678"
        search_bar = app.query_one(SearchBar)
        search_bar._enter_subject.on_next("metaphysics")
        await pilot.pause(0.5)

        mock_session_service.add_event.assert_called()
        event_type = mock_session_service.add_event.call_args[0][1]
        assert event_type == "search"


async def test_filter_changed_with_active_query_reruns_search(
    mock_search_service, mock_library_service
):
    """FilterChanged re-triggers search when a query is active.

    Updated for RxPY pipeline (plan 17-04): replaced direct app.query assignment
    with _enter_subject.on_next() so the query_stream has emitted (required for
    combine_latest). Then FilterChanged re-triggers via the _filter_subject.
    """
    app = make_app(search_service=mock_search_service, library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        # First, fire a query through the pipeline so combine_latest has a value
        search_bar = app.query_one(SearchBar)
        search_bar._enter_subject.on_next("epistemology")
        await pilot.pause(0.5)

        initial_count = mock_search_service.search.call_count
        assert initial_count >= 1

        # Now change filters -- should re-trigger search via combine_latest
        app.post_message(FilterChanged(filters=FilterSet(difficulty="advanced")))
        await pilot.pause(0.5)

        assert app.active_filters.difficulty == "advanced"
        assert mock_search_service.search.call_count > initial_count


async def test_filter_changed_with_no_query_does_not_search(
    mock_search_service, mock_library_service
):
    """FilterChanged does NOT re-run search when query is empty."""
    app = make_app(search_service=mock_search_service, library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(FilterChanged(filters=FilterSet(difficulty="introductory")))
        await pilot.pause(0.3)

        mock_search_service.search.assert_not_called()
        assert app.active_filters.difficulty == "introductory"


# ---------------------------------------------------------------------------
# Result Selection Tests
# ---------------------------------------------------------------------------


async def test_result_selected_updates_selected_index(mock_library_service, sample_citations):
    """ResultSelected message updates app.selected_index."""
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.results = sample_citations
        app.query_one(ResultsList).update_results(sample_citations)
        await pilot.pause(0.2)

        citation = sample_citations[0]
        app.post_message(ResultSelected(index=0, citation=citation))
        await pilot.pause(0.3)

        assert app.selected_index == 0


async def test_result_selected_loads_full_document_when_file_path(
    mock_library_service, sample_citations
):
    """ResultSelected loads full document content when citation has file_path."""
    mock_library_service.get_file_content.return_value = "Full document text here."
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        citation = sample_citations[0]  # Has file_path set
        app.post_message(ResultSelected(index=0, citation=citation))
        await pilot.pause(0.3)

        preview = app.query_one(PreviewPane)
        assert preview._current_content == "Full document text here."


async def test_result_selected_shows_citation_detail_when_no_file_path(mock_library_service):
    """ResultSelected falls back to citation detail panel when no file_path."""
    citation = Citation(
        index=1,
        title="Detached Citation",
        uri=None,
        text="A passage with no corresponding file on disk.",
        document_name=None,
        confidence=0.7,
        file_path=None,
    )
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(ResultSelected(index=0, citation=citation))
        await pilot.pause(0.3)

        preview = app.query_one(PreviewPane)
        assert preview._current_content is None  # show_citation_detail clears content


async def test_result_selected_shows_unavailable_when_content_is_none(
    mock_library_service, sample_citations
):
    """ResultSelected shows 'unavailable' when library_service returns None."""
    mock_library_service.get_file_content.return_value = None
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        citation = sample_citations[0]
        app.post_message(ResultSelected(index=0, citation=citation))
        await pilot.pause(0.3)

        preview = app.query_one(PreviewPane)
        assert preview._current_content is None  # show_unavailable clears content


async def test_result_selected_highlights_search_terms_in_document(
    mock_library_service, sample_citations
):
    """ResultSelected passes the current query as highlight_terms to show_document."""
    mock_library_service.get_file_content.return_value = "Content with virtue mentioned."
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query = "virtue"  # Set active search query
        citation = sample_citations[0]
        app.post_message(ResultSelected(index=0, citation=citation))
        await pilot.pause(0.3)

        # Content was loaded (not None), meaning highlight_terms were applied
        preview = app.query_one(PreviewPane)
        assert preview._current_content == "Content with virtue mentioned."


# ---------------------------------------------------------------------------
# File Selected (Nav Tree) Tests
# ---------------------------------------------------------------------------


async def test_file_selected_loads_document(mock_library_service):
    """FileSelected from nav tree loads document content into preview pane."""
    mock_library_service.get_file_content.return_value = "Lecture content from nav tree."
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(FileSelected(file_path="/library/Test.txt", filename="Test.txt"))
        await pilot.pause(0.3)

        preview = app.query_one(PreviewPane)
        assert preview._current_content == "Lecture content from nav tree."
        assert preview._current_file_path == "/library/Test.txt"


async def test_file_selected_shows_unavailable_when_no_content(mock_library_service):
    """FileSelected shows 'unavailable' when content returns None."""
    mock_library_service.get_file_content.return_value = None
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(FileSelected(file_path="/missing.txt", filename="missing.txt"))
        await pilot.pause(0.3)

        assert app.query_one(PreviewPane)._current_content is None


async def test_file_selected_no_library_service_shows_unavailable():
    """FileSelected with no library_service shows graceful 'unavailable' message."""
    app = make_app(library_service=None)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(FileSelected(file_path="/test.txt", filename="test.txt"))
        await pilot.pause(0.2)

        assert app.query_one(PreviewPane)._current_content is None


# ---------------------------------------------------------------------------
# Navigation Requested Tests
# ---------------------------------------------------------------------------


async def test_navigation_requested_course_calls_service(mock_library_service):
    """NavigationRequested for course calls get_files_by_course with correct name."""
    mock_library_service.get_files_by_course.return_value = [
        {"filename": f"File{i}.txt", "file_path": f"/lib/File{i}.txt"} for i in range(5)
    ]
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(NavigationRequested(course="OPAR"))
        await pilot.pause(0.3)

        mock_library_service.get_files_by_course.assert_called_with("OPAR")


async def test_navigation_requested_category_calls_service(mock_library_service):
    """NavigationRequested for category calls get_items_by_category with correct name."""
    mock_library_service.get_items_by_category.return_value = [
        {"filename": "Book.txt", "file_path": "/lib/Book.txt"}
    ]
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(NavigationRequested(category="book"))
        await pilot.pause(0.3)

        mock_library_service.get_items_by_category.assert_called_with("book")


async def test_navigation_requested_no_service_does_not_crash():
    """NavigationRequested with no library_service silently returns."""
    app = make_app(library_service=None)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(NavigationRequested(course="OPAR"))
        await pilot.pause(0.2)
        # No crash


# ---------------------------------------------------------------------------
# Bookmark Action Tests
# ---------------------------------------------------------------------------


async def test_toggle_bookmark_no_document_does_not_add_bookmark():
    """Toggling bookmark when no document is previewed leaves bookmarks unchanged."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        # No document loaded; _current_file_path is None
        await app.run_action("toggle_bookmark")
        await pilot.pause(0.2)
        assert app.bookmarks == []


async def test_toggle_bookmark_adds_bookmark(mock_library_service):
    """Toggling bookmark on a loaded document adds it to app.bookmarks."""
    mock_library_service.get_file_content.return_value = "Document text."
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(FileSelected(
            file_path="/library/OPAR - Lesson 01.txt",
            filename="OPAR - Lesson 01.txt",
        ))
        await pilot.pause(0.3)

        await app.run_action("toggle_bookmark")
        await pilot.pause(0.2)

        assert len(app.bookmarks) == 1
        assert app.bookmarks[0].file_path == "/library/OPAR - Lesson 01.txt"
        assert app.bookmarks[0].filename == "OPAR - Lesson 01.txt"


async def test_toggle_bookmark_removes_existing_bookmark(mock_library_service):
    """Toggling bookmark on an already-bookmarked document removes it."""
    mock_library_service.get_file_content.return_value = "Document text."
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        file_path = "/library/Ethics - Lesson 01.txt"
        app.bookmarks = [Bookmark(file_path=file_path, filename="Ethics - Lesson 01.txt")]

        app.post_message(FileSelected(file_path=file_path, filename="Ethics - Lesson 01.txt"))
        await pilot.pause(0.3)

        await app.run_action("toggle_bookmark")
        await pilot.pause(0.2)

        assert app.bookmarks == []


async def test_show_bookmarks_with_empty_list_shows_no_result_items():
    """action_show_bookmarks with empty bookmarks shows status, no ResultItems."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.run_action("show_bookmarks")
        await pilot.pause(0.2)
        assert len(list(app.query_one(ResultsList).query(ResultItem))) == 0


async def test_show_bookmarks_with_bookmarks_displays_as_citations():
    """action_show_bookmarks converts each bookmark to a ResultItem card."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.bookmarks = [
            Bookmark(file_path="/lib/A.txt", filename="A.txt"),
            Bookmark(file_path="/lib/B.txt", filename="B.txt"),
            Bookmark(file_path="/lib/C.txt", filename="C.txt"),
        ]
        await app.run_action("show_bookmarks")
        await pilot.pause(0.2)

        items = list(app.query_one(ResultsList).query(ResultItem))
        assert len(items) == 3


async def test_bookmark_watch_updates_status_bar():
    """watch_bookmarks updates the status bar when bookmarks change."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.bookmarks = [Bookmark(file_path="/lib/A.txt", filename="A.txt")]
        await pilot.pause(0.2)
        # Status bar updated without crash
        status = app.query_one("#status-bar")
        assert status is not None


# ---------------------------------------------------------------------------
# Session Action Tests
# ---------------------------------------------------------------------------


async def test_action_new_session_creates_session(mock_session_service):
    """action_new_session creates a session and stores its ID."""
    app = make_app(session_service=mock_session_service)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.action_new_session()
        await pilot.pause(0.2)

        mock_session_service.create_session.assert_called_once()
        assert app.active_session_id == "session-uuid-12345678"


async def test_action_new_session_no_service_does_not_crash():
    """action_new_session with no session_service does not crash."""
    app = make_app(session_service=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.action_new_session()
        assert app.active_session_id is None


async def test_action_save_session_no_service_does_not_crash():
    """action_save_session with no session_service does not crash."""
    app = make_app(session_service=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.action_save_session()
        # No crash


async def test_action_save_session_auto_creates_session_when_none(mock_session_service):
    """action_save_session creates a new session when none is active."""
    app = make_app(session_service=mock_session_service)
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.active_session_id is None
        await app.action_save_session()
        await pilot.pause(0.2)

        mock_session_service.create_session.assert_called_once()
        assert app.active_session_id == "session-uuid-12345678"


async def test_action_save_session_records_filter_and_bookmark_events(mock_session_service):
    """action_save_session adds exactly 2 note events (filter state + bookmarks)."""
    app = make_app(session_service=mock_session_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.active_session_id = "existing-session"
        app.active_filters = FilterSet(category="course")
        app.bookmarks = [Bookmark(file_path="/lib/A.txt", filename="A.txt")]

        await app.action_save_session()
        await pilot.pause(0.2)

        assert mock_session_service.add_event.call_count == 2
        calls = mock_session_service.add_event.call_args_list
        event_types = [c[0][1] for c in calls]
        assert all(t == "note" for t in event_types)
        payloads = [c[0][2]["type"] for c in calls]
        assert "filter_state" in payloads
        assert "bookmarks" in payloads


async def test_action_load_session_no_service_does_not_crash():
    """action_load_session with no session_service does not crash."""
    app = make_app(session_service=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.action_load_session()


async def test_action_load_session_no_sessions_does_not_crash(mock_session_service):
    """action_load_session with empty session list does not crash."""
    mock_session_service.list_sessions.return_value = []
    app = make_app(session_service=mock_session_service)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.action_load_session()
        assert app.active_session_id is None


async def test_action_load_session_restores_bookmarks(mock_session_service):
    """action_load_session restores bookmarks from note events."""
    mock_session_service.list_sessions.return_value = [
        {"id": "sess-001", "name": "My Session"}
    ]
    mock_session_service.get_events.return_value = [
        {
            "event_type": "note",
            "payload": {
                "type": "bookmarks",
                "bookmarks": [{"file_path": "/lib/A.txt", "filename": "A.txt", "note": ""}],
            },
        },
    ]
    app = make_app(session_service=mock_session_service)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.action_load_session()
        await pilot.pause(0.2)

        assert len(app.bookmarks) == 1
        assert app.bookmarks[0].file_path == "/lib/A.txt"
        assert app.active_session_id == "sess-001"


async def test_action_load_session_restores_filter_state(mock_session_service):
    """action_load_session restores FilterSet from note events."""
    mock_session_service.list_sessions.return_value = [
        {"id": "sess-001", "name": "Session"}
    ]
    mock_session_service.get_events.return_value = [
        {
            "event_type": "note",
            "payload": {
                "type": "filter_state",
                "filters": {"category": "book", "course": None, "difficulty": None},
            },
        },
    ]
    app = make_app(session_service=mock_session_service)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.action_load_session()
        await pilot.pause(0.2)

        assert app.active_filters.category == "book"


async def test_action_load_session_restores_search_history(mock_session_service):
    """action_load_session reconstructs search_history from search events."""
    mock_session_service.list_sessions.return_value = [
        {"id": "sess-001", "name": "Session"}
    ]
    mock_session_service.get_events.return_value = [
        {"event_type": "search", "payload": {"query": "virtue", "result_count": 3}},
        {"event_type": "search", "payload": {"query": "consciousness", "result_count": 5}},
    ]
    app = make_app(session_service=mock_session_service)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.action_load_session()
        await pilot.pause(0.2)

        assert "virtue" in app.search_history
        assert "consciousness" in app.search_history


async def test_action_export_session_no_active_does_not_crash():
    """action_export_session with no active session does not crash."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.action_export_session()


async def test_action_export_session_with_active_shows_hint(mock_session_service):
    """action_export_session with active session shows CLI hint notification."""
    app = make_app(session_service=mock_session_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.active_session_id = "active-session"
        await app.action_export_session()
        # No crash; notification was posted


# ---------------------------------------------------------------------------
# Synthesis Action Tests
# ---------------------------------------------------------------------------


async def test_action_synthesize_with_fewer_than_2_results_does_not_call_service(
    mock_search_service,
):
    """Synthesis requires at least 2 results; fewer shows warning without calling service."""
    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.results = []
        await app.action_synthesize_results()
        mock_search_service.synthesize.assert_not_called()


async def test_action_synthesize_no_service_does_not_crash(sample_citations):
    """Synthesis with no search_service shows warning without crash."""
    app = make_app(search_service=None)
    async with app.run_test(size=(120, 40)) as pilot:
        app.results = sample_citations
        await app.action_synthesize_results()
        # No crash


async def test_action_synthesize_calls_service_with_results(mock_search_service, sample_citations):
    """Synthesis calls search_service.synthesize with current query and results."""
    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.results = sample_citations
        app.query = "virtue in epistemology"
        await app.action_synthesize_results()
        await pilot.pause(0.3)

        mock_search_service.synthesize.assert_called_once_with(
            "virtue in epistemology", sample_citations
        )


# ---------------------------------------------------------------------------
# UI Action Tests
# ---------------------------------------------------------------------------


async def test_action_focus_search_focuses_search_bar():
    """action_focus_search puts keyboard focus on the SearchBar."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.run_action("focus_search")
        await pilot.pause(0.1)
        assert app.focused is app.query_one(SearchBar)


async def test_action_toggle_nav_toggles_hidden_class():
    """action_toggle_nav toggles 'hidden' CSS class on the nav-pane."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        nav = app.query_one("#nav-pane")
        assert not nav.has_class("hidden")

        await app.run_action("toggle_nav")
        await pilot.pause(0.1)
        assert nav.has_class("hidden")

        await app.run_action("toggle_nav")
        await pilot.pause(0.1)
        assert not nav.has_class("hidden")


async def test_action_clear_search_resets_state(mock_search_service, sample_citations):
    """action_clear_search resets query, results, and selected_index to defaults."""
    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query = "previous query"
        app.results = sample_citations
        app.selected_index = 1

        await app.run_action("clear_search")
        await pilot.pause(0.2)

        assert app.query == ""
        assert app.results == []
        assert app.selected_index is None


async def test_action_toggle_fullscreen_preview_toggles_class():
    """action_toggle_fullscreen_preview toggles 'fullscreen-preview' on the app."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        assert not app.has_class("fullscreen-preview")

        await app.run_action("toggle_fullscreen_preview")
        await pilot.pause(0.1)
        assert app.has_class("fullscreen-preview")

        await app.run_action("toggle_fullscreen_preview")
        await pilot.pause(0.1)
        assert not app.has_class("fullscreen-preview")


async def test_action_show_shortcuts_does_not_crash():
    """action_show_shortcuts writes keyboard reference to preview pane."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.run_action("show_shortcuts")
        await pilot.pause(0.1)
        assert app.query_one(PreviewPane) is not None


async def test_action_reset_filters_does_not_crash():
    """action_reset_filters clears filter panel without crashing."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.run_action("reset_filters")
        await pilot.pause(0.1)


async def test_action_browse_categories_focuses_nav_tree():
    """action_browse_categories focuses the NavTree widget."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.run_action("browse_categories")
        await pilot.pause(0.1)
        assert app.focused is app.query_one(NavTree)


async def test_action_browse_courses_focuses_nav_tree():
    """action_browse_courses focuses the NavTree widget."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.run_action("browse_courses")
        await pilot.pause(0.1)
        assert app.focused is app.query_one(NavTree)


async def test_ctrl_f_key_binding_focuses_search():
    """Pressing Ctrl+F focuses the search bar (key binding active)."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+f")
        await pilot.pause(0.1)
        assert app.focused is app.query_one(SearchBar)


async def test_ctrl_b_key_binding_toggles_nav():
    """Pressing Ctrl+B toggles the nav pane visibility."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        nav = app.query_one("#nav-pane")
        await pilot.press("ctrl+b")
        await pilot.pause(0.1)
        assert nav.has_class("hidden")


async def test_escape_key_binding_clears_search():
    """Pressing Escape clears the current search."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.query = "some query"
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert app.query == ""


# ---------------------------------------------------------------------------
# Responsive Layout Tests
# ---------------------------------------------------------------------------


async def test_on_resize_applies_exactly_one_layout_class():
    """on_resize always applies exactly one of the three layout classes."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.on_resize()
        await pilot.pause(0.1)

        layout_classes = [
            c for c in ("layout-wide", "layout-medium", "layout-narrow")
            if app.has_class(c)
        ]
        assert len(layout_classes) == 1


async def test_on_resize_wide_applies_layout_wide():
    """Width >= 140 applies layout-wide class."""
    app = make_app()
    async with app.run_test(size=(160, 40)) as pilot:
        app.on_resize()
        await pilot.pause(0.1)
        assert app.has_class("layout-wide")


async def test_on_resize_medium_applies_layout_medium():
    """Width 80-139 applies layout-medium class (two-pane, nav hidden)."""
    app = make_app()
    async with app.run_test(size=(100, 40)) as pilot:
        app.on_resize()
        await pilot.pause(0.1)
        assert app.has_class("layout-medium")


async def test_on_resize_narrow_applies_layout_narrow():
    """Width < 80 applies layout-narrow class (stacked single-column)."""
    app = make_app()
    async with app.run_test(size=(60, 40)) as pilot:
        app.on_resize()
        await pilot.pause(0.1)
        assert app.has_class("layout-narrow")


async def test_on_resize_clears_previous_layout_class():
    """on_resize removes stale layout classes before applying the new one."""
    app = make_app()
    async with app.run_test(size=(100, 40)) as pilot:
        app.add_class("layout-wide")  # Simulate wrong state
        app.on_resize()
        await pilot.pause(0.1)

        assert not app.has_class("layout-wide")
        assert app.has_class("layout-medium")


# ---------------------------------------------------------------------------
# PreviewPane Widget Tests
# ---------------------------------------------------------------------------


async def test_preview_show_document_stores_content():
    """show_document stores content and file_path for citation jump."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        preview.show_document("Hello world content!", "/path/to/doc.txt")

        assert preview._current_content == "Hello world content!"
        assert preview._current_file_path == "/path/to/doc.txt"


async def test_preview_show_document_with_highlight_terms_does_not_crash():
    """show_document with highlight_terms applies highlighting without error."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        preview.show_document(
            "Philosophy is about consciousness and existence.",
            "/path/doc.txt",
            highlight_terms=["consciousness", "existence"],
        )
        assert preview._current_content == "Philosophy is about consciousness and existence."


async def test_preview_show_document_with_empty_highlight_list():
    """show_document with empty highlight_terms list does not crash."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        preview.show_document("Content.", "/path/doc.txt", highlight_terms=[])
        assert preview._current_content == "Content."


async def test_preview_show_citation_detail_clears_current_content(sample_citations):
    """show_citation_detail clears _current_content (disables scroll_to_citation)."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        preview.show_document("Some content", "/path/doc.txt")
        assert preview._current_content is not None

        preview.show_citation_detail(sample_citations[0])
        assert preview._current_content is None


async def test_preview_show_citation_detail_with_full_metadata(sample_citations):
    """show_citation_detail handles citations with course, year, difficulty metadata."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        preview.show_citation_detail(sample_citations[0])  # Has course, year, difficulty
        assert preview._current_content is None


async def test_preview_show_citation_detail_with_no_metadata():
    """show_citation_detail handles citations with no metadata dict."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        citation = Citation(1, "Test.txt", None, "Passage text.", None, 0.5, metadata=None)
        preview.show_citation_detail(citation)
        assert preview._current_content is None


async def test_preview_scroll_to_citation_noop_when_no_content():
    """scroll_to_citation is a no-op when no document is loaded."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        assert preview._current_content is None
        preview.scroll_to_citation("Some passage text")  # Should not raise


async def test_preview_scroll_to_citation_finds_passage():
    """scroll_to_citation scrolls to the line containing the passage."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        content = "Line one.\nLine two with the passage.\nLine three."
        preview.show_document(content, "/path/doc.txt")
        preview.scroll_to_citation("Line two with the passage.")  # Should not raise


async def test_preview_scroll_to_citation_not_found_writes_message():
    """scroll_to_citation writes a not-found message when passage is absent."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        preview.show_document("Line one.\nLine two.", "/path/doc.txt")
        # Passage not in content -- should write a "not found" message without raising
        preview.scroll_to_citation("Completely different passage XYZ123")


async def test_preview_show_placeholder_clears_content():
    """show_placeholder sets _current_content to None."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        preview.show_document("Content", "/path/doc.txt")
        preview.show_placeholder()
        assert preview._current_content is None


async def test_preview_show_placeholder_custom_message():
    """show_placeholder accepts and displays a custom message."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        preview.show_placeholder("Loading document...")
        assert preview._current_content is None


async def test_preview_show_unavailable_clears_content():
    """show_unavailable sets _current_content to None."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        preview = app.query_one(PreviewPane)
        preview.show_document("Content", "/path/doc.txt")
        preview.show_unavailable()
        assert preview._current_content is None


# ---------------------------------------------------------------------------
# ResultsList Widget Tests
# ---------------------------------------------------------------------------


async def test_results_list_empty_shows_no_result_items():
    """update_results([]) mounts status widget, not ResultItem widgets."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one(ResultsList).update_results([])
        await pilot.pause(0.2)
        assert len(list(app.query_one(ResultsList).query(ResultItem))) == 0


async def test_results_list_mounts_one_item_per_citation(sample_citations):
    """update_results(citations) mounts exactly one ResultItem per citation."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one(ResultsList).update_results(sample_citations)
        await pilot.pause(0.2)

        items = list(app.query_one(ResultsList).query(ResultItem))
        assert len(items) == len(sample_citations)


async def test_results_list_update_status_replaces_all_children():
    """update_status replaces all children with a single status widget."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        results_list = app.query_one(ResultsList)
        results_list.update_status("Searching...")
        await pilot.pause(0.1)
        assert len(list(app.query_one(ResultsList).query(ResultItem))) == 0


async def test_results_list_select_index_adds_selected_class(sample_citations):
    """select_index adds '-selected' CSS class to the target ResultItem."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        results_list = app.query_one(ResultsList)
        results_list.update_results(sample_citations)
        await pilot.pause(0.2)

        results_list.select_index(0)
        await pilot.pause(0.1)

        assert app.query_one("#result-0", ResultItem).has_class("-selected")


async def test_results_list_select_index_clears_previous_selection(sample_citations):
    """select_index removes '-selected' from the previously selected item."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        results_list = app.query_one(ResultsList)
        results_list.update_results(sample_citations)
        await pilot.pause(0.2)

        results_list.select_index(0)
        await pilot.pause(0.1)
        results_list.select_index(1)
        await pilot.pause(0.1)

        assert not app.query_one("#result-0", ResultItem).has_class("-selected")
        assert app.query_one("#result-1", ResultItem).has_class("-selected")


# ---------------------------------------------------------------------------
# ResultItem Widget — Raw Gemini ID Guard Tests
# ---------------------------------------------------------------------------


async def test_result_item_raw_id_shows_unresolved_placeholder():
    """ResultItem with a raw Gemini ID title (no '.') shows '[Unresolved file #N]'."""
    raw_citation = Citation(
        index=1,
        title="l38iajfzqsjq",  # No "." — raw Gemini file ID
        uri=None,
        text="A passage about rationality and volition.",
        document_name=None,
        confidence=0.7,
    )
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one(ResultsList).update_results([raw_citation])
        await pilot.pause(0.2)

        item = app.query_one("#result-0", ResultItem)
        rendered_text = item.content.plain
        assert "[Unresolved file #1]" in rendered_text
        assert "l38iajfzqsjq" not in rendered_text


async def test_result_item_raw_id_placeholder_uses_one_based_index():
    """Unresolved placeholder number is 1-based: result_index 0 → '#1', 1 → '#2'."""
    citations = [
        Citation(
            index=1, title="valid.txt", uri=None,
            text="First passage.", document_name=None, confidence=0.9,
        ),
        Citation(
            index=2, title="p0e9lyp0n9mz", uri=None,  # Raw ID at position 1
            text="Second passage.", document_name=None, confidence=0.7,
        ),
    ]
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one(ResultsList).update_results(citations)
        await pilot.pause(0.2)

        item0 = app.query_one("#result-0", ResultItem)
        item1 = app.query_one("#result-1", ResultItem)

        assert "valid.txt" in item0.content.plain
        assert "[Unresolved file #2]" in item1.content.plain


async def test_result_item_resolved_filename_displays_unchanged():
    """ResultItem with a filename (has '.') shows the title without any substitution."""
    normal_citation = Citation(
        index=1,
        title="OPAR - Lesson 01.txt",
        uri=None,
        text="Philosophy is the science of existence.",
        document_name=None,
        confidence=0.9,
        file_path="/library/OPAR - Lesson 01.txt",
    )
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one(ResultsList).update_results([normal_citation])
        await pilot.pause(0.2)

        item = app.query_one("#result-0", ResultItem)
        rendered_text = item.content.plain
        assert "OPAR - Lesson 01.txt" in rendered_text
        assert "[Unresolved" not in rendered_text


async def test_result_item_raw_id_still_shows_passage_excerpt():
    """Even with an unresolved title, the passage excerpt still appears in the card."""
    passage = "The validation of reason is the validation of the senses."
    raw_citation = Citation(
        index=1, title="5696txrhqdue", uri=None,
        text=passage, document_name=None, confidence=0.6,
    )
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one(ResultsList).update_results([raw_citation])
        await pilot.pause(0.2)

        item = app.query_one("#result-0", ResultItem)
        rendered_text = item.content.plain
        # Placeholder replaces the title, but the excerpt is still shown
        assert "[Unresolved file #1]" in rendered_text
        assert passage[:40] in rendered_text  # Excerpt appears in card


# ---------------------------------------------------------------------------
# SearchBar Widget Tests
# ---------------------------------------------------------------------------


async def test_search_bar_has_placeholder_text():
    """SearchBar placeholder contains 'Search' hint text."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(SearchBar)
        assert "Search" in bar.placeholder


async def test_search_bar_initial_history_is_empty():
    """SearchBar starts with empty history and index -1."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(SearchBar)
        assert bar._history == []
        assert bar._history_index == -1


async def test_search_bar_enter_adds_to_history():
    """Pressing Enter records query in search history.

    Updated for RxPY pipeline (plan 17-04): replaced _fire_search() (removed)
    with typing + Enter via pilot, which triggers on_key history management.
    """
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(SearchBar)
        bar.focus()
        await pilot.pause(0.05)

        for char in "virtue":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause(0.1)

        assert "virtue" in bar._history


async def test_search_bar_enter_deduplicates_consecutive():
    """Pressing Enter twice with same query adds it to history only once.

    Updated for RxPY pipeline (plan 17-04): replaced _fire_search() (removed)
    with typing + Enter via pilot, which triggers on_key history management.
    """
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(SearchBar)
        bar.focus()
        await pilot.pause(0.05)

        # Type "virtue" and press Enter
        for char in "virtue":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause(0.1)

        # Press Enter again with same value (should not duplicate)
        await pilot.press("enter")
        await pilot.pause(0.1)

        # Clear and type "consciousness"
        bar.value = ""
        await pilot.pause(0.05)
        for char in "consciousness":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause(0.1)

        assert bar._history == ["virtue", "consciousness"]


async def test_search_bar_history_up_arrow_navigates_backward():
    """Up arrow navigates to the most recent history entry."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(SearchBar)
        bar._history = ["query1", "query2", "query3"]

        await pilot.press("ctrl+f")  # Focus search bar
        await pilot.pause(0.1)
        await pilot.press("up")
        await pilot.pause(0.1)

        assert bar.value == "query3"


async def test_search_bar_history_up_arrow_continues_backward():
    """Successive up presses navigate further back in history."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(SearchBar)
        bar._history = ["query1", "query2", "query3"]

        await pilot.press("ctrl+f")
        await pilot.pause(0.1)
        await pilot.press("up")
        await pilot.pause(0.1)
        await pilot.press("up")
        await pilot.pause(0.1)

        assert bar.value == "query2"


async def test_search_bar_history_down_arrow_past_end_clears():
    """Down arrow past the end of history clears the search bar."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(SearchBar)
        bar._history = ["query1"]
        bar._history_index = 0
        bar.value = "query1"

        await pilot.press("ctrl+f")
        await pilot.pause(0.1)
        await pilot.press("down")
        await pilot.pause(0.1)

        assert bar.value == ""
        assert bar._history_index == -1


async def test_search_bar_clear_and_reset():
    """clear_and_reset sets value to '' and resets history index."""
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(SearchBar)
        bar.value = "some query"
        bar._history_index = 2

        bar.clear_and_reset()
        await pilot.pause(0.1)

        assert bar.value == ""
        assert bar._history_index == -1


async def test_search_bar_click_result_posts_result_selected(sample_citations):
    """Clicking a ResultItem posts ResultSelected to the app."""
    app = make_app()
    received_selections = []

    def capture(event: ResultSelected):
        received_selections.append(event.index)

    async with app.run_test(size=(120, 40)) as pilot:
        results_list = app.query_one(ResultsList)
        results_list.update_results(sample_citations)
        await pilot.pause(0.2)

        await pilot.click("#result-0")
        await pilot.pause(0.2)

        # selected_index should be updated by the app handler
        assert app.selected_index == 0


# ---------------------------------------------------------------------------
# ObjlibCommands Provider Tests
# ---------------------------------------------------------------------------


def test_objlib_commands_has_15_entries():
    """ObjlibCommands.COMMANDS dict has exactly 15 entries."""
    from objlib.tui.providers import ObjlibCommands

    assert len(ObjlibCommands.COMMANDS) == 15


def test_objlib_commands_all_actions_exist_on_app():
    """Every ObjlibCommands action name corresponds to an action_ method on ObjlibApp."""
    from objlib.tui.providers import ObjlibCommands

    for command_name, action_name in ObjlibCommands.COMMANDS.items():
        method_name = f"action_{action_name}"
        assert hasattr(ObjlibApp, method_name), (
            f"ObjlibApp missing '{method_name}' for command '{command_name}'"
        )


def test_objlib_commands_includes_key_actions():
    """ObjlibCommands includes essential commands for search, browse, and sessions."""
    from objlib.tui.providers import ObjlibCommands

    commands = ObjlibCommands.COMMANDS
    assert "Search Library" in commands
    assert "New Session" in commands
    assert "Bookmark Current Document" in commands
    assert "Toggle Fullscreen Preview" in commands


# ---------------------------------------------------------------------------
# run_tui Entry Point Tests
# ---------------------------------------------------------------------------


def test_run_tui_missing_api_key_raises_system_exit():
    """run_tui raises SystemExit(1) when no API key is found in keyring."""
    with patch("keyring.get_password", return_value=None):
        from objlib.tui import run_tui

        with pytest.raises(SystemExit) as exc_info:
            run_tui(db_path="data/library.db", store_name="test-store")

        assert exc_info.value.code == 1


def test_run_tui_store_resolution_failure_falls_back_gracefully():
    """run_tui continues with the display name when store resolution raises."""
    captured_store = {}

    def fake_search_service(**kwargs):
        captured_store["name"] = kwargs.get("store_resource_name")
        return object()

    with (
        patch("keyring.get_password", return_value="fake-api-key"),
        patch("google.genai.Client", side_effect=Exception("No network")),
        patch("objlib.services.SearchService", side_effect=fake_search_service),
        patch("objlib.services.LibraryService", return_value=object()),
        patch("objlib.services.SessionService", return_value=object()),
        patch.object(ObjlibApp, "run"),
    ):
        from objlib.tui import run_tui

        run_tui(db_path="data/library.db", store_name="my-store")

    # Fallback: store_resource_name should be the display name
    assert captured_store.get("name") == "my-store"


# ---------------------------------------------------------------------------
# Error-path UATs — exercises error conditions so telemetry logs are emitted
# ---------------------------------------------------------------------------


async def test_search_service_exception_shows_error_in_results(mock_library_service):
    """When search_service.search raises, the results list shows the error message."""
    svc = AsyncMock()
    svc.search.side_effect = RuntimeError("Gemini API quota exceeded")
    app = make_app(search_service=svc, library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(SearchRequested(query="virtue"))
        await pilot.pause(0.5)

        # Error path: no ResultItems — status widget replaced them
        results_list = app.query_one(ResultsList)
        assert len(list(results_list.query(ResultItem))) == 0


async def test_library_service_exception_during_file_preview_does_not_crash(
    mock_library_service, sample_citations
):
    """When library_service.get_file_content raises, the app handles it gracefully."""
    mock_library_service.get_file_content.side_effect = OSError("Disk not mounted")
    app = make_app(library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        citation = sample_citations[0]
        app.post_message(ResultSelected(index=0, citation=citation))
        await pilot.pause(0.3)
        # App still alive and responsive after the error
        assert app.query_one(PreviewPane) is not None


async def test_session_service_exception_during_save_does_not_crash(
    mock_session_service,
):
    """When session_service.add_event raises, action_save_session handles it gracefully."""
    mock_session_service.add_event.side_effect = RuntimeError("DB locked")
    app = make_app(session_service=mock_session_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.active_session_id = "active-session"
        await app.action_save_session()
        await pilot.pause(0.2)
        # App is still alive after the error
        assert app.query_one(ResultsList) is not None
