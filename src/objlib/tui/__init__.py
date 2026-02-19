"""Objectivism Library Interactive TUI.

Provides a Textual-based terminal interface for browsing, searching,
and exploring the Objectivism Library with live search, split-pane
views, and session management.
"""

from __future__ import annotations

DEFAULT_DB_PATH = "data/library.db"
DEFAULT_STORE_NAME = "objectivism-library-test"


def run_tui(
    db_path: str = DEFAULT_DB_PATH,
    store_name: str = DEFAULT_STORE_NAME,
) -> None:
    """Initialize services and launch the TUI application.

    Resolves the Gemini store name, creates service instances,
    and runs the Textual app. All imports are deferred for fast
    module loading.

    Args:
        db_path: Path to the SQLite library database.
        store_name: Display name of the Gemini File Search store.
    """
    import keyring

    from objlib.tui.app import ObjlibApp

    # Get API key from system keyring
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        print(
            "Error: No Gemini API key found in keyring.\n"
            "Set it with: keyring set objlib-gemini api_key"
        )
        raise SystemExit(1)

    # Resolve store name to resource name (network call)
    try:
        from objlib.search import GeminiSearchClient

        client = GeminiSearchClient(api_key=api_key)
        resolved_store = client.resolve_store_name(store_name)
    except Exception as exc:
        print(f"Warning: Could not resolve store name: {exc}")
        resolved_store = None

    # Create service instances (services facade from plan 07-01)
    # Services may not be available yet -- handle gracefully
    search_service = None
    library_service = None
    session_service = None

    try:
        from objlib.services import LibraryService, SearchService, SessionService

        search_service = SearchService(
            api_key=api_key,
            store_name=resolved_store or store_name,
            db_path=db_path,
        )
        library_service = LibraryService(db_path=db_path)
        session_service = SessionService(db_path=db_path)
    except (ImportError, Exception) as exc:
        print(f"Note: Services not fully available: {exc}")
        print("TUI will launch with limited functionality.")

    # Create and run the app
    app = ObjlibApp(
        search_service=search_service,
        library_service=library_service,
        session_service=session_service,
    )
    app.run()
