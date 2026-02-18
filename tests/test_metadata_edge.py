"""MetadataExtractor edge case tests.

Covers graceful degradation, pattern boundary conditions, folder
metadata extraction, filename-over-folder precedence, missing fields,
unicode handling, and extraction failure flags.

These tests complement tests/test_metadata.py by focusing on edge cases
NOT covered there: unrecognized filenames, extra dashes, no dashes,
folder-vs-filename precedence, missing lesson numbers, triple-digit
lessons, non-.txt extensions, unicode, whitespace trimming, and the
_unparsed_filename flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from objlib.metadata import MetadataExtractor
from objlib.models import MetadataQuality


@pytest.fixture
def extractor() -> MetadataExtractor:
    """Fresh MetadataExtractor with no mappings."""
    return MetadataExtractor()


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Unrecognized filenames degrade to MINIMAL, not NONE."""

    def test_unrecognized_filename_gets_minimal_quality(self, extractor) -> None:
        """Filename like 'random_notes.txt' gets MINIMAL quality with topic from stem."""
        file_path = Path("/lib/random_notes.txt")
        library_root = Path("/lib")

        metadata, quality = extractor.extract(file_path, library_root)

        assert quality == MetadataQuality.MINIMAL
        assert metadata.get("topic") == "random notes"

    def test_filename_with_no_dashes(self, extractor) -> None:
        """'JustAFilename.txt' degrades gracefully to MINIMAL."""
        file_path = Path("/lib/JustAFilename.txt")
        library_root = Path("/lib")

        metadata, quality = extractor.extract(file_path, library_root)

        assert quality == MetadataQuality.MINIMAL
        assert metadata.get("_unparsed_filename") is True
        assert metadata.get("topic") is not None

    def test_extraction_failure_flags(self, extractor) -> None:
        """Unrecognized filename has _unparsed_filename: True in metadata."""
        file_path = Path("/lib/some_random_file.txt")
        library_root = Path("/lib")

        metadata, _quality = extractor.extract(file_path, library_root)

        assert metadata.get("_unparsed_filename") is True
        assert metadata.get("raw_filename") == "some_random_file"


# ---------------------------------------------------------------------------
# Pattern matching: simple pattern
# ---------------------------------------------------------------------------


class TestSimplePattern:
    """SIMPLE_PATTERN boundary cases."""

    def test_simple_pattern_three_parts(self, extractor) -> None:
        """'Course Name - Lesson 01 - Topic Name.txt' extracts all three fields."""
        file_path = Path("/lib/Courses/CN/Course Name - Lesson 01 - Topic Name.txt")
        library_root = Path("/lib")

        metadata, quality = extractor.extract(file_path, library_root)

        assert metadata["course"] == "Course Name"
        assert metadata["lesson_number"] == "01"
        assert metadata["topic"] == "Topic Name"
        assert quality == MetadataQuality.COMPLETE

    def test_missing_lesson_number(self, extractor) -> None:
        """'Course Name - Introduction to Topic.txt' has no lesson number pattern.

        Without 'Lesson N' the simple pattern won't match. The filename
        will be treated as unrecognized at the filename level, but if it's
        under Courses/, the folder gives a course name and stem gives topic.
        """
        file_path = Path("/lib/Courses/Course Name/Course Name - Introduction to Topic.txt")
        library_root = Path("/lib")

        metadata, quality = extractor.extract(file_path, library_root)

        # The simple pattern requires "Lesson N" so it won't match.
        # Folder extraction gives course; stem gives topic via fallback.
        assert metadata.get("course") == "Course Name"
        assert metadata.get("topic") is not None
        assert metadata.get("lesson_number") is None

    def test_lesson_number_double_digits(self, extractor) -> None:
        """'Course - Lesson 10 - Topic.txt' extracts lesson_number=10."""
        file_path = Path("/lib/Courses/C/Course - Lesson 10 - Topic.txt")
        library_root = Path("/lib")

        metadata, _quality = extractor.extract(file_path, library_root)

        assert metadata["lesson_number"] == "10"

    def test_lesson_number_triple_digits(self, extractor) -> None:
        """'Course - Lesson 100 - Topic.txt' extracts lesson_number=100."""
        file_path = Path("/lib/Courses/C/Course - Lesson 100 - Topic.txt")
        library_root = Path("/lib")

        metadata, _quality = extractor.extract(file_path, library_root)

        assert metadata["lesson_number"] == "100"


# ---------------------------------------------------------------------------
# Pattern matching: complex pattern
# ---------------------------------------------------------------------------


class TestComplexPattern:
    """COMPLEX_PATTERN boundary cases."""

    def test_complex_pattern_year_quarter_week(self, extractor) -> None:
        """Full complex pattern extracts year, quarter, week, topic."""
        file_path = Path(
            "/lib/Courses/Seminar/Year2/Q2/"
            "Seminar - Year 2 - Q3 - Week 5 - Ethics of Capitalism.txt"
        )
        library_root = Path("/lib")

        metadata, quality = extractor.extract(file_path, library_root)

        assert metadata["course"] == "Seminar"
        assert metadata["year"] == "2"
        assert metadata["quarter"] == "3"
        assert metadata["week"] == "5"
        assert metadata["topic"] == "Ethics of Capitalism"
        assert quality == MetadataQuality.COMPLETE


# ---------------------------------------------------------------------------
# Edge case filenames
# ---------------------------------------------------------------------------


class TestFilenameEdgeCases:
    """Unusual filename patterns handled gracefully."""

    def test_filename_with_extra_dashes(self, extractor) -> None:
        """Extra dashes beyond expected pattern segments are handled gracefully."""
        file_path = Path(
            "/lib/Courses/C/Course - Sub-Topic - Part 1 - Extra - Stuff.txt"
        )
        library_root = Path("/lib")

        metadata, quality = extractor.extract(file_path, library_root)

        # The simple pattern requires "Lesson N" which is absent, so
        # this falls through to unrecognized. Folder gives course.
        assert metadata.get("course") == "C"
        assert metadata.get("topic") is not None
        assert quality in (MetadataQuality.PARTIAL, MetadataQuality.MINIMAL)

    def test_whitespace_in_course_name(self, extractor) -> None:
        """Leading/trailing whitespace in course name is trimmed."""
        # The regex .strip() handles whitespace in course capture group
        file_path = Path(
            "/lib/Courses/TC/  Course Name  - Lesson 01 - Topic.txt"
        )
        library_root = Path("/lib")

        metadata, _quality = extractor.extract(file_path, library_root)

        assert metadata["course"] == "Course Name"

    def test_txt_extension_required(self, extractor) -> None:
        """Non-.txt extension still produces metadata from stem (graceful)."""
        file_path = Path("/lib/document.pdf")
        library_root = Path("/lib")

        metadata, quality = extractor.extract(file_path, library_root)

        # Won't match any .txt pattern but still extracts topic from stem
        assert metadata.get("topic") is not None or metadata.get("raw_filename") is not None

    def test_unicode_in_filename(self, extractor) -> None:
        """Unicode characters in filename don't cause crashes."""
        file_path = Path("/lib/Courses/Phil/Aristotle's Metaphysics \u2013 An Overview.txt")
        library_root = Path("/lib")

        # Should not raise
        metadata, quality = extractor.extract(file_path, library_root)

        assert metadata is not None
        assert quality is not None
        # Topic should contain what it could parse from the stem
        assert metadata.get("topic") is not None or metadata.get("raw_filename") is not None


# ---------------------------------------------------------------------------
# Folder metadata extraction
# ---------------------------------------------------------------------------


class TestFolderMetadata:
    """Folder hierarchy metadata extraction edge cases."""

    def test_folder_metadata_extraction(self, extractor) -> None:
        """File under Courses/My Course/subfolder/ extracts course from folder."""
        file_path = Path("/lib/Courses/My Course/subfolder/file.txt")
        library_root = Path("/lib")

        metadata, _quality = extractor.extract(file_path, library_root)

        assert metadata.get("category") == "course"
        assert metadata.get("course") == "My Course"

    def test_folder_overridden_by_filename(self, extractor) -> None:
        """When both folder and filename provide course, filename wins (per [01-02])."""
        file_path = Path(
            "/lib/Courses/Folder Course/"
            "Filename Course - Lesson 01 - Topic.txt"
        )
        library_root = Path("/lib")

        metadata, _quality = extractor.extract(file_path, library_root)

        # Per decision [01-02]: filename takes precedence on overlap
        assert metadata["course"] == "Filename Course"

    def test_file_in_root_gets_unknown_category(self, extractor) -> None:
        """File directly in library root gets category='unknown'."""
        file_path = Path("/lib/orphan.txt")
        library_root = Path("/lib")

        metadata, _quality = extractor.extract(file_path, library_root)

        assert metadata.get("category") == "unknown"

    def test_file_in_motm_folder(self, extractor) -> None:
        """File under MOTM/ gets category='motm' from folder detection."""
        file_path = Path("/lib/MOTM/some_file.txt")
        library_root = Path("/lib")

        metadata, _quality = extractor.extract(file_path, library_root)

        assert metadata.get("category") == "motm"

    def test_file_in_books_folder(self, extractor) -> None:
        """File under Books/ gets category='book' from folder detection."""
        file_path = Path("/lib/Books/some_book.txt")
        library_root = Path("/lib")

        metadata, _quality = extractor.extract(file_path, library_root)

        assert metadata.get("category") == "book"
