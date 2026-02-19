"""Command palette provider for Objectivism Library TUI.

Registers all major TUI actions as fuzzy-searchable commands accessible
via Ctrl+P. Uses Textual's Provider/Hit API for the built-in command
palette widget.
"""

from __future__ import annotations

from functools import partial

from textual.command import Hit, Hits, Provider


class ObjlibCommands(Provider):
    """Command palette provider exposing all TUI actions.

    Maps human-readable command names to App action methods. The
    ``search`` method fuzzy-matches user input against command names
    and yields scored Hits that invoke the corresponding action.
    """

    COMMANDS: dict[str, str] = {
        "Search Library": "focus_search",
        "Clear Search": "clear_search",
        "Toggle Navigation Panel": "toggle_nav",
        "Browse by Category": "browse_categories",
        "Browse by Course": "browse_courses",
        "Reset Filters": "reset_filters",
        "Bookmark Current Document": "toggle_bookmark",
        "View Bookmarks": "show_bookmarks",
        "New Session": "new_session",
        "Save Session": "save_session",
        "Load Session": "load_session",
        "Export Session": "export_session",
        "Synthesize Results": "synthesize_results",
        "Toggle Fullscreen Preview": "toggle_fullscreen_preview",
        "Show Keyboard Shortcuts": "show_shortcuts",
    }

    async def search(self, query: str) -> Hits:
        """Fuzzy-match user input against registered commands.

        Args:
            query: User's typed input in the command palette.

        Yields:
            Hit objects for each command whose name fuzzy-matches
            the query, scored by match quality.
        """
        matcher = self.matcher(query)
        for name, action in self.COMMANDS.items():
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    partial(self.app.run_action, action),
                )
