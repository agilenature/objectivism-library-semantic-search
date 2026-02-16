"""Metadata extraction from folder hierarchy and filenames.

Extracts structured metadata from Objectivism Library file paths using
pre-compiled regex patterns. Supports four naming conventions:
  - Simple Course (41%): {Course} - Lesson {N} - {Topic}.txt
  - Complex Course (rare): {Course} - Year {N} - Q{N} - Week {N} - {Topic}.txt
  - MOTM (25%): MOTM_YYYY-MM-DD_Topic.txt
  - Peikoff Podcast (18%): Episode {N} [ID].txt

Quality grading assigns COMPLETE/PARTIAL/MINIMAL/NONE based on how many
fields were successfully extracted.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from objlib.models import MetadataQuality

logger = logging.getLogger(__name__)

# CRITICAL: Use \d+ not \d{2} -- handles single-digit, double-digit,
# and triple-digit lesson numbers
SIMPLE_PATTERN = re.compile(
    r"^(?P<course>.+?) - Lesson (?P<lesson>\d+) - (?P<topic>.+?)\.txt$"
)
COMPLEX_PATTERN = re.compile(
    r"^(?P<course>.+?) - Year (?P<year>\d+) - Q(?P<quarter>\d+)"
    r" - Week (?P<week>\d+) - (?P<topic>.+?)\.txt$"
)
# MOTM pattern: MOTM_2019-07-28_Topic-With-Dashes.txt
MOTM_PATTERN = re.compile(
    r"^MOTM_(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})_(?P<topic>.+?)\.txt$"
)
# Peikoff Podcast patterns:
# Pattern 1: Episode 356 [1000332668759].txt
# Pattern 2: Episode 097 – 2/1/2010 [1000386969198].txt
PODCAST_PATTERN = re.compile(
    r"^Episode (?P<episode>\d+) \[(?P<id>\d+)\]\.txt$"
)
PODCAST_PATTERN_WITH_DATE = re.compile(
    r"^Episode (?P<episode>\d+) – (?P<date>[\d/]+) \[(?P<id>\d+)\]\.txt$"
)
# Folder detection for complex pattern: Year{N}/Q{N}/ subfolders
YEAR_FOLDER = re.compile(r"^Year\s*(\d+)$")
QUARTER_FOLDER = re.compile(r"^Q(\d+)$")


class MetadataExtractor:
    """Extracts metadata from file paths using regex patterns and folder hierarchy.

    Usage:
        extractor = MetadataExtractor()
        metadata, quality = extractor.extract(file_path, library_root)
    """

    def __init__(self, metadata_mappings: dict | None = None) -> None:
        """Initialize the metadata extractor.

        Args:
            metadata_mappings: Optional dict from metadata_mappings.json
                for course-level enrichment (difficulty, instructor, etc.)
        """
        self.metadata_mappings = metadata_mappings or {}

    def extract(
        self, file_path: Path, library_root: Path
    ) -> tuple[dict, MetadataQuality]:
        """Extract metadata from a file path relative to the library root.

        Main entry point. Combines folder-level and filename-level metadata,
        enriches from mappings if available, and grades quality.

        Args:
            file_path: Absolute path to the file.
            library_root: Absolute path to the library root directory.

        Returns:
            Tuple of (metadata_dict, MetadataQuality).
        """
        try:
            relative_path = file_path.relative_to(library_root)
        except ValueError:
            relative_path = Path(file_path.name)

        folder_meta = self._extract_folder_metadata(relative_path)
        filename_meta = self._extract_filename_metadata(file_path.name)

        # Merge: filename takes precedence for overlapping keys,
        # but folder metadata fills in gaps
        metadata: dict = {}
        metadata.update(folder_meta)
        metadata.update(filename_meta)

        # If filename extraction found a course, prefer it; otherwise
        # keep the folder-derived course name
        if not filename_meta.get("course") and folder_meta.get("course"):
            metadata["course"] = folder_meta["course"]

        metadata = self._enrich_from_mappings(metadata)
        quality = self._grade_quality(metadata)

        return metadata, quality

    def _extract_folder_metadata(self, relative_path: Path) -> dict:
        """Parse folder components between library root and filename.

        Detects:
          - Whether file is inside Courses/ directory
          - Course name from parent folder (simple) or grandparent (complex)
          - Year/Quarter from Year{N}/Q{N}/ subfolders
          - Top-level category (course, book, motm, podcast, unknown)

        Args:
            relative_path: Path relative to library root.

        Returns:
            Dict with extracted folder-level fields.
        """
        parts = relative_path.parts
        metadata: dict = {}

        if len(parts) < 2:
            # File is directly in library root -- minimal folder info
            metadata["category"] = "unknown"
            return metadata

        # Detect top-level category from first folder component
        top_folder = parts[0].lower()
        category_map = {
            "courses": "course",
            "books": "book",
            "motm": "motm",
            "podcasts": "podcast",
        }
        metadata["category"] = category_map.get(top_folder, "unknown")

        # For files inside Courses/ directory, extract course name
        if metadata["category"] == "course" and len(parts) >= 3:
            # Check for complex pattern: Courses/{CourseName}/Year{N}/Q{N}/file.txt
            year_val = None
            quarter_val = None
            course_name = parts[1]  # Default: immediate subfolder of Courses/

            for i, part in enumerate(parts[2:-1], start=2):
                year_match = YEAR_FOLDER.match(part)
                if year_match:
                    year_val = year_match.group(1)
                    # Course name is the folder before Year folder
                    course_name = parts[i - 1]
                    continue

                quarter_match = QUARTER_FOLDER.match(part)
                if quarter_match:
                    quarter_val = quarter_match.group(1)

            metadata["course"] = course_name
            if year_val:
                metadata["folder_year"] = year_val
            if quarter_val:
                metadata["folder_quarter"] = quarter_val

        elif metadata["category"] == "course" and len(parts) == 2:
            # File directly inside Courses/ with no subfolder
            metadata["_unparsed_folder"] = True

        return metadata

    def _extract_filename_metadata(self, filename: str) -> dict:
        """Extract metadata from the filename using regex patterns.

        Tries patterns in order: COMPLEX, SIMPLE, MOTM, PODCAST.
        If no match, returns minimal metadata with unparsed flag.

        Args:
            filename: The filename (not full path).

        Returns:
            Dict with extracted filename-level fields.
        """
        # Try complex course pattern first (most specific)
        match = COMPLEX_PATTERN.match(filename)
        if match:
            topic = match.group("topic").strip()
            topic = topic.replace("_", " ").strip()
            return {
                "course": match.group("course").strip(),
                "year": match.group("year"),
                "quarter": match.group("quarter"),
                "week": match.group("week"),
                "topic": topic,
            }

        # Try simple course pattern
        match = SIMPLE_PATTERN.match(filename)
        if match:
            topic = match.group("topic").strip()
            topic = topic.replace("_", " ").strip()
            return {
                "course": match.group("course").strip(),
                "lesson_number": match.group("lesson"),
                "topic": topic,
            }

        # Try MOTM pattern: MOTM_YYYY-MM-DD_Topic.txt
        match = MOTM_PATTERN.match(filename)
        if match:
            topic = match.group("topic").strip()
            topic = topic.replace("-", " ").replace("_", " ").strip()
            date_str = f"{match.group('year')}-{match.group('month')}-{match.group('day')}"
            return {
                "series": "MOTM",
                "date": date_str,
                "year": match.group("year"),
                "month": match.group("month"),
                "day": match.group("day"),
                "topic": topic,
            }

        # Try Peikoff Podcast pattern with date: Episode N – M/D/YYYY [ID].txt
        match = PODCAST_PATTERN_WITH_DATE.match(filename)
        if match:
            return {
                "series": "Peikoff Podcast",
                "episode_number": match.group("episode"),
                "episode_date": match.group("date"),
                "episode_id": match.group("id"),
            }

        # Try Peikoff Podcast pattern: Episode N [ID].txt
        match = PODCAST_PATTERN.match(filename)
        if match:
            return {
                "series": "Peikoff Podcast",
                "episode_number": match.group("episode"),
                "episode_id": match.group("id"),
            }

        # No pattern matched -- graceful degradation
        # Strip extension and use filename as raw data
        stem = Path(filename).stem
        metadata: dict = {
            "raw_filename": stem,
            "_unparsed_filename": True,
        }

        # Try to extract at least a topic from the filename
        if stem:
            metadata["topic"] = stem.replace("_", " ").strip()

        return metadata

    def _grade_quality(self, metadata: dict) -> MetadataQuality:
        """Grade metadata quality based on extracted fields.

        Returns:
            COMPLETE: courses with structure, MOTM with date+topic, podcasts with episode
            PARTIAL: has course+topic OR series without full structure
            MINIMAL: has course OR topic OR series (but incomplete)
            NONE: no recognizable fields extracted
        """
        has_course = bool(metadata.get("course"))
        series = metadata.get("series")
        has_series = bool(series)
        has_topic = bool(metadata.get("topic"))
        has_lesson = bool(metadata.get("lesson_number"))
        has_hierarchy = all(
            metadata.get(f) for f in ("year", "quarter", "week")
        )
        has_date = bool(metadata.get("date"))
        has_episode = bool(metadata.get("episode_number"))

        # COMPLETE: structured course content or series with identifying info
        if has_course and (has_lesson or has_hierarchy) and has_topic:
            return MetadataQuality.COMPLETE
        if series == "MOTM" and has_date and has_topic:
            return MetadataQuality.COMPLETE
        if series == "Peikoff Podcast" and has_episode:
            return MetadataQuality.COMPLETE

        # PARTIAL: has main identifier + topic but missing structure
        if has_course and has_topic:
            return MetadataQuality.PARTIAL
        if has_series and has_topic:
            return MetadataQuality.PARTIAL

        # MINIMAL: has something but incomplete
        if has_course or has_topic or has_series:
            return MetadataQuality.MINIMAL

        return MetadataQuality.NONE

    def _enrich_from_mappings(self, metadata: dict) -> dict:
        """Enrich metadata with course-level mappings if available.

        Looks up the course name in metadata_mappings and adds any
        additional fields (difficulty, instructor, etc.) that are not
        already present in the metadata.

        Does not overwrite extracted fields -- only adds missing ones.

        Args:
            metadata: Existing metadata dict.

        Returns:
            Enriched metadata dict (same object, modified in place).
        """
        course_name = metadata.get("course")
        if not course_name:
            return metadata

        courses = self.metadata_mappings.get("courses", {})
        course_info = courses.get(course_name)
        if not course_info:
            return metadata

        for key, value in course_info.items():
            if key not in metadata:
                metadata[key] = value

        return metadata
