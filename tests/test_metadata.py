"""Metadata extraction tests.

Validates:
  FOUN-04: Folder hierarchy metadata extraction
  FOUN-05: Filename pattern matching
"""

from __future__ import annotations

from pathlib import Path

from objlib.metadata import MetadataExtractor
from objlib.models import MetadataQuality


def test_simple_pattern_basic(metadata_extractor: MetadataExtractor) -> None:
    """Parse standard Course - Lesson N - Topic filename."""
    file_path = Path("/lib/Courses/Test/Test Course - Lesson 01 - Introduction.txt")
    library_root = Path("/lib")

    metadata, quality = metadata_extractor.extract(file_path, library_root)

    assert metadata["course"] == "Test Course"
    assert metadata["lesson_number"] == "01"
    assert metadata["topic"] == "Introduction"


def test_simple_pattern_single_digit(metadata_extractor: MetadataExtractor) -> None:
    """Parse filename with single-digit lesson number (tests \\d+ regex)."""
    file_path = Path("/lib/Courses/Test/Course A - Lesson 3 - Topic.txt")
    library_root = Path("/lib")

    metadata, _quality = metadata_extractor.extract(file_path, library_root)

    assert metadata["lesson_number"] == "3"


def test_simple_pattern_triple_digit(metadata_extractor: MetadataExtractor) -> None:
    """Parse filename with triple-digit lesson number."""
    file_path = Path("/lib/Courses/Test/Course B - Lesson 100 - Topic.txt")
    library_root = Path("/lib")

    metadata, _quality = metadata_extractor.extract(file_path, library_root)

    assert metadata["lesson_number"] == "100"


def test_complex_pattern(metadata_extractor: MetadataExtractor) -> None:
    """Parse Year/Q/Week filename with folder structure."""
    file_path = Path(
        "/lib/Courses/Seminar/Year1/Q1/"
        "Seminar - Year 1 - Q1 - Week 1 - Topic.txt"
    )
    library_root = Path("/lib")

    metadata, quality = metadata_extractor.extract(file_path, library_root)

    assert metadata["course"] == "Seminar"
    assert metadata["year"] == "1"
    assert metadata["quarter"] == "1"
    assert metadata["week"] == "1"
    assert metadata["topic"] == "Topic"
    assert quality == MetadataQuality.COMPLETE


def test_quality_complete(metadata_extractor: MetadataExtractor) -> None:
    """File matching simple pattern gets COMPLETE quality."""
    file_path = Path("/lib/Courses/Test/Course - Lesson 01 - Topic.txt")
    library_root = Path("/lib")

    _metadata, quality = metadata_extractor.extract(file_path, library_root)

    assert quality == MetadataQuality.COMPLETE


def test_quality_partial(metadata_extractor: MetadataExtractor) -> None:
    """File with course folder but no lesson in filename gets PARTIAL quality.

    A file that doesn't match any filename pattern but lives under
    Courses/CourseName/ still gets course from folder + topic from filename stem.
    """
    file_path = Path("/lib/Courses/My Course/some topic file.txt")
    library_root = Path("/lib")

    metadata, quality = metadata_extractor.extract(file_path, library_root)

    # Folder extraction gives course, filename stem gives topic
    assert metadata.get("course") == "My Course"
    assert metadata.get("topic") is not None
    assert quality == MetadataQuality.PARTIAL


def test_quality_minimal_unrecognized(metadata_extractor: MetadataExtractor) -> None:
    """File matching no pattern at root level gets MINIMAL quality.

    The extractor's graceful degradation uses the filename stem as a topic,
    so even unrecognized files get at least MINIMAL (has topic but no course).
    """
    file_path = Path("/lib/random_notes.txt")
    library_root = Path("/lib")

    metadata, quality = metadata_extractor.extract(file_path, library_root)

    # Stem "random_notes" becomes topic -> MINIMAL (topic but no course)
    assert metadata.get("topic") is not None
    assert quality == MetadataQuality.MINIMAL


def test_quality_none(metadata_extractor: MetadataExtractor) -> None:
    """Quality grader returns NONE when metadata has no course and no topic."""
    # Directly test the grading logic: empty metadata -> NONE
    quality = metadata_extractor._grade_quality({})
    assert quality == MetadataQuality.NONE

    quality2 = metadata_extractor._grade_quality({"raw_filename": "x"})
    assert quality2 == MetadataQuality.NONE


def test_topic_cleanup(metadata_extractor: MetadataExtractor) -> None:
    """Verify underscores replaced and whitespace stripped in topic."""
    file_path = Path("/lib/Courses/Test/Course - Lesson 01 - My_Topic_Name .txt")
    library_root = Path("/lib")

    metadata, _quality = metadata_extractor.extract(file_path, library_root)

    assert metadata["topic"] == "My Topic Name"


def test_folder_course_extraction(metadata_extractor: MetadataExtractor) -> None:
    """Verify course name extracted from parent folder for files in Courses/."""
    file_path = Path("/lib/Courses/Philosophy 101/some_file.txt")
    library_root = Path("/lib")

    metadata, _quality = metadata_extractor.extract(file_path, library_root)

    assert metadata.get("course") == "Philosophy 101"


def test_category_detection(metadata_extractor: MetadataExtractor) -> None:
    """Verify Courses/ directory -> category='course'."""
    file_path = Path("/lib/Courses/Test/Course - Lesson 01 - Topic.txt")
    library_root = Path("/lib")

    metadata, _quality = metadata_extractor.extract(file_path, library_root)

    assert metadata.get("category") == "course"
