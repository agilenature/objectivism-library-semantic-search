"""Navigation tree widget for library browsing.

Displays a category/course/file hierarchy with count badges.
Course files are lazy-loaded on node expansion. Selecting nodes
posts FileSelected or NavigationRequested messages for the App
to handle.
"""

from __future__ import annotations

from textual.widgets import Tree

from objlib.tui.messages import FileSelected, NavigationRequested
from objlib.tui.telemetry import get_telemetry


class NavTree(Tree):
    """Hierarchical tree view of the library organized by category and course.

    Top-level nodes are categories (e.g., 'course', 'book', 'motm') with
    file counts. The 'course' category has children for each course name.
    Course nodes lazy-load their files when expanded. Leaf file nodes
    post FileSelected messages when selected.

    The tree does NOT hold a reference to LibraryService -- it accesses
    ``self.app.library_service`` so the App owns the service lifecycle.
    """

    DEFAULT_CSS = """
    NavTree {
        width: 100%;
        height: 1fr;
        background: $surface;
        scrollbar-gutter: stable;
    }
    """

    def __init__(self) -> None:
        super().__init__("Library", id="nav-tree")

    async def populate(self, library_service: object) -> None:
        """Build the category/course tree from library data.

        Args:
            library_service: LibraryService instance (accessed via App).
        """
        with get_telemetry().span("widget.nav_populate") as span:
            self.clear()

            categories = await library_service.get_categories()  # type: ignore[attr-defined]
            course_count = 0

            for cat_name, count in categories:
                cat_node = self.root.add(
                    f"{cat_name} ({count})",
                    data={"type": "category", "name": cat_name},
                )

                # For the "course" category, also load course names as children
                if cat_name == "course":
                    courses = await library_service.get_courses()  # type: ignore[attr-defined]
                    course_count = len(courses)
                    for course_name, course_count_item in courses:
                        cat_node.add(
                            f"{course_name} ({course_count_item})",
                            data={"type": "course", "name": course_name},
                        )

            # Bookmarks node at the top level
            self.root.add(
                "Bookmarks",
                data={"type": "bookmarks"},
            )

            # Expand root so categories are visible immediately
            self.root.expand()

            span.set_attribute("nav.category_count", len(categories))
            span.set_attribute("nav.course_count", course_count)
            get_telemetry().log.info(
                f"nav tree populated categories={len(categories)} courses={course_count}"
            )

    async def expand_course(
        self, course_name: str, node: object, library_service: object
    ) -> None:
        """Lazy-load files for a course when its node is expanded.

        Only fetches files the first time the node is expanded (checks
        whether the node already has children).

        Args:
            course_name: Course name to fetch files for.
            node: The TreeNode being expanded.
            library_service: LibraryService instance.
        """
        with get_telemetry().span("widget.nav_course_expanded") as span:
            span.set_attribute("nav.course", course_name)
            files = await library_service.get_files_by_course(course_name)  # type: ignore[attr-defined]
            for file_dict in files:
                filename = file_dict.get("filename", "")
                file_path = file_dict.get("file_path", "")
                node.add_leaf(  # type: ignore[attr-defined]
                    filename,
                    data={
                        "type": "file",
                        "file_path": file_path,
                        "filename": filename,
                    },
                )
            span.set_attribute("nav.file_count", len(files))
            get_telemetry().log.info(
                f"course expanded course={course_name!r} file_count={len(files)}"
            )

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Post messages when a tree node is selected."""
        data = event.node.data
        if data is None:
            return

        node_type = data.get("type")

        if node_type == "file":
            get_telemetry().log.info(
                f"nav node selected type=file filename={data['filename']!r}"
            )
            self.post_message(
                FileSelected(
                    file_path=data["file_path"],
                    filename=data["filename"],
                )
            )
        elif node_type == "category":
            get_telemetry().log.info(
                f"nav node selected type=category name={data['name']!r}"
            )
            self.post_message(
                NavigationRequested(category=data["name"])
            )
        elif node_type == "course":
            get_telemetry().log.info(
                f"nav node selected type=course name={data['name']!r}"
            )
            self.post_message(
                NavigationRequested(course=data["name"])
            )

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Lazy-load course files when a course node is first expanded."""
        data = event.node.data
        if data is None:
            return

        if data.get("type") == "course" and not event.node.children:
            # Lazy load -- fetch files for this course
            library_service = self.app.library_service  # type: ignore[attr-defined]
            if library_service is not None:
                self.app.call_later(
                    self.expand_course,
                    data["name"],
                    event.node,
                    library_service,
                )
