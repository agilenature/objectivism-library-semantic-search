"""Pre-implementation UAT baseline for TUI behavioral invariants.

These 7 tests capture the exact behavior of the current (pre-RxPY) TUI
implementation. After the RxPY migration (plan 17-03), the identical
assertions must pass to confirm behavioral parity.

The tests drive input through pilot.press() (NOT app.post_message) to
exercise the full SearchBar -> debounce -> App pipeline end-to-end.

Contract values captured here (search call counts, timing windows, history navigation search delta)
are the gate for plan 17-04.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from objlib.models import Citation, SearchResult
from objlib.tui.app import ObjlibApp
from objlib.tui.messages import FilterChanged
from objlib.tui.state import FilterSet
from objlib.tui.widgets import SearchBar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_citations() -> list[Citation]:
    """Two test Citation objects for search result simulation."""
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
# Behavioral Invariant Tests (7 total)
# ---------------------------------------------------------------------------


async def test_uat_debounce_fires_once(mock_search_service):
    """Invariant 1: Rapid typing fires exactly 1 search after debounce window.

    Contract:
    - 0 searches while typing (before debounce expires)
    - Exactly 1 search after debounce window elapses
    - Search called with full accumulated query "hello"
    """
    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        # Focus the search bar
        search_bar = app.query_one(SearchBar)
        search_bar.focus()
        await pilot.pause(0.05)

        # Type "hello" rapidly -- each character within 300ms debounce window
        for char in "hello":
            await pilot.press(char)

        # BEFORE debounce: no search should have fired
        await pilot.pause(0.05)
        assert mock_search_service.search.call_count == 0, (
            f"Expected 0 searches before debounce, got {mock_search_service.search.call_count}"
        )

        # AFTER debounce: wait for debounce (300ms) + processing margin
        await pilot.pause(0.5)
        assert mock_search_service.search.call_count == 1, (
            f"Expected exactly 1 search after debounce, got {mock_search_service.search.call_count}"
        )

        # Verify search was called with the full query
        call_args = mock_search_service.search.call_args
        assert call_args[0][0] == "hello", (
            f"Expected search query 'hello', got {call_args[0][0]!r}"
        )

        print(f"DEBOUNCE_CONTRACT: searches_before=0, searches_after=1, query='hello'")


async def test_uat_enter_fires_immediately(mock_search_service):
    """Invariant 2: Enter fires search immediately; no double-fire after debounce.

    Contract:
    - 1 search within 50ms of Enter press
    - Still only 1 search after the debounce window passes (no double-fire)
    """
    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar.focus()
        await pilot.pause(0.05)

        # Type "hello" then press Enter
        for char in "hello":
            await pilot.press(char)
        await pilot.press("enter")

        # Enter fires immediately -- check within 50ms
        await pilot.pause(0.05)
        count_after_enter = mock_search_service.search.call_count
        assert count_after_enter == 1, (
            f"Expected 1 search within 50ms of Enter, got {count_after_enter}"
        )

        # Wait through the debounce window -- should NOT fire again (no double-fire)
        await pilot.pause(0.5)
        count_after_debounce = mock_search_service.search.call_count
        assert count_after_debounce == 1, (
            f"Expected still 1 search after debounce (no double-fire), got {count_after_debounce}"
        )

        print(f"ENTER_CONTRACT: immediate_count=1, post_debounce_count=1")


async def test_uat_stale_cancellation(mock_search_service):
    """Invariant 3: @work(exclusive=True) cancels stale in-flight searches.

    Contract:
    - Two rapid Enter searches ("alpha" then "beta") both fire
    - After completion, app.query reflects latest query ("beta")
    - @work(exclusive=True) cancels "alpha" when "beta" arrives

    We track whether alpha's search completes or gets cancelled by using
    a side_effect that records start/end events.
    """
    call_log = []

    async def tracked_search(query, **kwargs):
        call_log.append(("start", query))
        # Simulate API latency so alpha is "in-flight" when beta arrives
        await asyncio.sleep(0.3)
        call_log.append(("end", query))
        return SearchResult(
            response_text=f"Results for {query}",
            citations=[],
            query=query,
            metadata_filter=None,
        )

    mock_search_service.search.side_effect = tracked_search

    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar.focus()
        await pilot.pause(0.05)

        # Fire "alpha" via Enter
        for char in "alpha":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause(0.05)

        # Clear and fire "beta" via Enter while alpha is in-flight
        # Select all text and type over it
        search_bar.value = ""
        await pilot.pause(0.05)
        for char in "beta":
            await pilot.press(char)
        await pilot.press("enter")

        # Wait for all searches to complete
        await pilot.pause(1.0)

        # app.query reflects the latest query
        assert app.query == "beta", (
            f"Expected app.query='beta', got {app.query!r}"
        )

        # Log the observed behavior for the contract
        starts = [q for op, q in call_log if op == "start"]
        ends = [q for op, q in call_log if op == "end"]
        print(f"STALE_CANCEL_CONTRACT: starts={starts}, ends={ends}")
        print(f"  app.query={app.query!r}")

        # Both searches were started (Enter fires immediately)
        assert "alpha" in starts, "Expected alpha to start"
        assert "beta" in starts, "Expected beta to start"

        # Beta must have completed (it was the latest)
        assert "beta" in ends, "Expected beta to complete"


async def test_uat_filter_triggers_search(mock_search_service):
    """Invariant 4: Changing filters while a query is active re-triggers search.

    Contract:
    - Initial search via Enter: 1 call
    - FilterChanged message: search count increases to 2
    """
    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar.focus()
        await pilot.pause(0.05)

        # Type "virtue" then Enter for initial search
        for char in "virtue":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause(0.5)

        initial_count = mock_search_service.search.call_count
        assert initial_count >= 1, (
            f"Expected at least 1 search after Enter, got {initial_count}"
        )

        # Post a FilterChanged message to simulate filter panel interaction
        app.post_message(FilterChanged(filters=FilterSet(difficulty="advanced")))
        await pilot.pause(0.5)

        filter_count = mock_search_service.search.call_count
        assert filter_count > initial_count, (
            f"Expected search count to increase after filter change: "
            f"initial={initial_count}, after_filter={filter_count}"
        )

        print(f"FILTER_CONTRACT: initial_searches={initial_count}, after_filter={filter_count}")


async def test_uat_history_navigation(mock_search_service):
    """Invariant 5: Up/Down arrows navigate search history.

    Contract:
    - After searching "alpha" then "beta", Up arrow cycles through history
    - Down arrow past end returns to empty string
    - Measured: HISTORY_NAV_SEARCH_DELTA = searches fired during navigation
      (because setting self.value triggers on_input_changed -> debounce -> search)
    """
    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar.focus()
        await pilot.pause(0.05)

        # Build history: search "alpha" then "beta"
        for char in "alpha":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause(0.5)

        # Clear and search "beta"
        search_bar.value = ""
        await pilot.pause(0.05)
        for char in "beta":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause(0.5)

        searches_before_nav = mock_search_service.search.call_count
        print(f"  searches before nav: {searches_before_nav}")

        # Press Up -- should show most recent history item ("beta")
        await pilot.press("up")
        await pilot.pause(0.05)
        value_after_up1 = search_bar.value
        print(f"  after Up #1: value={value_after_up1!r}")

        # Press Up again -- should show "alpha"
        await pilot.press("up")
        await pilot.pause(0.05)
        value_after_up2 = search_bar.value
        print(f"  after Up #2: value={value_after_up2!r}")

        # Press Down -- should move forward (back to "beta")
        await pilot.press("down")
        await pilot.pause(0.05)
        value_after_down1 = search_bar.value
        print(f"  after Down #1: value={value_after_down1!r}")

        # Press Down again -- past end, should clear to ""
        await pilot.press("down")
        await pilot.pause(0.05)
        value_after_down2 = search_bar.value
        print(f"  after Down #2: value={value_after_down2!r}")

        # Wait for any debounce timers from history navigation to fire
        await pilot.pause(0.5)
        searches_after_nav = mock_search_service.search.call_count
        history_nav_search_delta = searches_after_nav - searches_before_nav

        # Assert history navigation works
        assert value_after_up1 == "beta", (
            f"First Up should show 'beta' (most recent), got {value_after_up1!r}"
        )
        assert value_after_up2 == "alpha", (
            f"Second Up should show 'alpha' (older), got {value_after_up2!r}"
        )
        assert value_after_down1 == "beta", (
            f"First Down should return to 'beta', got {value_after_down1!r}"
        )
        assert value_after_down2 == "", (
            f"Second Down past end should clear to '', got {value_after_down2!r}"
        )

        print(f"HISTORY_NAV_CONTRACT: up1={value_after_up1!r}, up2={value_after_up2!r}, "
              f"down1={value_after_down1!r}, down2={value_after_down2!r}")
        print(f"HISTORY_NAV_SEARCH_DELTA: {history_nav_search_delta}")


async def test_uat_empty_query_clears_immediately(mock_search_service):
    """Invariant 6: action_clear_search clears results immediately (not after debounce).

    Contract:
    - After a search with results, action_clear_search clears within 50ms
    - app.results == [] and app.query == "" immediately after clear
    """
    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar.focus()
        await pilot.pause(0.05)

        # Do a search to populate results
        for char in "virtue":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause(0.5)

        # Verify results exist
        assert len(app.results) > 0, "Expected results after search"
        assert app.query == "virtue", f"Expected query='virtue', got {app.query!r}"

        # Clear via the app action (same as pressing Escape)
        app.action_clear_search()

        # Wait only 50ms -- clear must be immediate, NOT debounced
        await pilot.pause(0.05)

        assert app.results == [], (
            f"Expected results=[] within 50ms of clear, got {len(app.results)} results"
        )
        assert app.query == "", (
            f"Expected query='' within 50ms of clear, got {app.query!r}"
        )
        assert app.selected_index is None, (
            f"Expected selected_index=None after clear, got {app.selected_index}"
        )

        print(f"CLEAR_CONTRACT: results_empty=True, query_empty=True, selected_index=None")


async def test_uat_error_containment(mock_search_service):
    """Invariant 7: Search errors are contained; app state resets cleanly.

    Contract:
    - When search service raises RuntimeError, the error is caught
    - app.is_searching resets to False (via finally block)
    - App does not crash
    """
    mock_search_service.search.side_effect = RuntimeError("API failure")

    app = make_app(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar.focus()
        await pilot.pause(0.05)

        # Type "fail" and press Enter to trigger search
        for char in "fail":
            await pilot.press(char)
        await pilot.press("enter")

        # Wait for the search to complete (error path)
        await pilot.pause(0.5)

        # is_searching must reset to False (via finally block in _run_search)
        assert app.is_searching is False, (
            f"Expected is_searching=False after error, got {app.is_searching}"
        )

        # App is still functional -- not crashed
        # Verify the search was attempted
        assert mock_search_service.search.call_count >= 1, (
            "Expected at least 1 search attempt"
        )

        print(f"ERROR_CONTRACT: is_searching={app.is_searching}, "
              f"search_calls={mock_search_service.search.call_count}")
