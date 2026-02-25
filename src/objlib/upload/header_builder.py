"""Identity metadata header builder for Gemini File Search uploads.

Builds a structured identity section that is PREPENDED before the existing
[AI Analysis] header from content_preparer.py. The identity fields provide
discriminating signals (filename, class number, course, topic, tags) that
Gemini uses for semantic search ranking.

Root cause (Phase 16.3-01 diagnosis): the AI Analysis header contains only
generic semantic concepts shared across many files. For ~440 "Other-stem"
files (course class-number files where topic == filename stem), the class
number exists ONLY in the filename — not in the transcript, not in the AI
analysis header. Injecting identity fields into the indexed content allows
Gemini to distinguish Class 09-02 from Class 09-01.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)


def build_identity_header(file_path: str, conn: sqlite3.Connection) -> str:
    """Build identity metadata header to prepend to file content.

    Returns a structured header with Title/Course/Class/Topic/Tags fields.
    Designed to be prepended BEFORE the existing [AI Analysis] header
    in content_preparer.py's prepare_enriched_content() output.

    The combined content structure for a Category A (class-number) file::

        --- DOCUMENT METADATA ---
        Title: Objectivist Logic - Class 09-02
        Course: Objectivist Logic
        Class: Class 09-02
        Topic: Objectivist Logic - Class 09-02
        Tags: concept_formation induction logic objective_reality ...
        --- END METADATA ---

        [AI Analysis]
        Category: ... | Difficulty: ...
        ...

    Args:
        file_path: The file_path value as stored in the files table
            (absolute path on disk).
        conn: Open SQLite connection to library.db.

    Returns:
        Formatted identity header string ending with newline,
        or empty string if file not found in DB.
    """
    # Look up file metadata
    row = conn.execute(
        "SELECT filename, metadata_json FROM files WHERE file_path = ?",
        (file_path,),
    ).fetchone()

    if row is None:
        logger.warning("build_identity_header: file not found in DB: %s", file_path)
        return ""

    filename, metadata_json_str = row
    stem = PurePosixPath(filename).stem  # e.g. "Objectivist Logic - Class 09-02"

    # Parse scanner metadata
    metadata = {}
    if metadata_json_str:
        try:
            metadata = json.loads(metadata_json_str)
        except (json.JSONDecodeError, TypeError):
            logger.warning("build_identity_header: invalid metadata_json for %s", filename)

    # Extract course from parent directory
    # file_path: /Volumes/.../Courses/Objectivist Logic/Objectivist Logic - Class 09-02.txt
    course = PurePosixPath(file_path).parent.name

    # Extract class identifier from filename (e.g., "Class 09-02")
    class_match = re.search(r"Class\s+(\d{2}-\d{2})", filename)
    class_id = f"Class {class_match.group(1)}" if class_match else None

    # Scanner topic
    scanner_topic = metadata.get("topic", "")

    # Primary topics from file_primary_topics table
    topic_rows = conn.execute(
        "SELECT topic_tag FROM file_primary_topics WHERE file_path = ?",
        (file_path,),
    ).fetchall()
    primary_topics = [r[0] for r in topic_rows]

    # Session-specific aspects from file_metadata_ai (distinguishes between
    # semantically similar files in the same course/series)
    ai_row = conn.execute(
        "SELECT metadata_json FROM file_metadata_ai WHERE file_path = ? AND is_current = 1",
        (file_path,),
    ).fetchone()
    topic_aspects: list[str] = []
    if ai_row and ai_row[0]:
        try:
            ai_meta = json.loads(ai_row[0])
            topic_aspects = ai_meta.get("topic_aspects", []) or []
        except (json.JSONDecodeError, TypeError):
            pass

    # Build header
    lines = ["--- DOCUMENT METADATA ---"]
    lines.append(f"Title: {stem}")
    lines.append(f"Course: {course}")

    if class_id:
        lines.append(f"Class: {class_id}")

    if scanner_topic:
        lines.append(f"Topic: {scanner_topic}")

    if primary_topics:
        lines.append(f"Tags: {' '.join(primary_topics)}")

    if topic_aspects:
        lines.append(f"Aspects: {'; '.join(topic_aspects)}")

    lines.append("--- END METADATA ---")

    header = "\n".join(lines) + "\n"

    logger.debug(
        "build_identity_header: %s -> %d bytes (%d tags, %d aspects, class=%s)",
        filename,
        len(header.encode("utf-8")),
        len(primary_topics),
        len(topic_aspects),
        class_id or "none",
    )

    return header
