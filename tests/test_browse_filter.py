"""Tests for browse and filter database query methods.

Validates hierarchical navigation (categories -> courses -> files)
and metadata-only filter queries against SQLite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from objlib.database import Database
from objlib.models import FileRecord, FileStatus, MetadataQuality


@pytest.fixture
def browse_db(tmp_path: Path) -> Database:
    """Create a database with varied test data for browse/filter testing.

    Inserts ~10 files across multiple categories:
    - 3 files: category=course, course=OPAR (years 2021, 2022, 2023)
    - 2 files: category=course, course=ITOE
    - 2 files: category=motm
    - 2 files: category=book
    - 1 file:  category=course, course=OPAR, status=LOCAL_DELETE (excluded)
    """
    db_path = tmp_path / "browse_test.db"
    db = Database(db_path)

    records = [
        # OPAR course files (3 active)
        FileRecord(
            file_path="/courses/opar/lesson01.txt",
            content_hash="opar1",
            filename="OPAR - Lesson 01 - Existence.txt",
            file_size=5000,
            metadata_json=json.dumps({
                "category": "course",
                "course": "OPAR",
                "year": 2021,
                "quarter": 1,
                "week": 1,
                "lesson_number": 1,
                "difficulty": "introductory",
            }),
            metadata_quality=MetadataQuality.COMPLETE,
        ),
        FileRecord(
            file_path="/courses/opar/lesson02.txt",
            content_hash="opar2",
            filename="OPAR - Lesson 02 - Consciousness.txt",
            file_size=6000,
            metadata_json=json.dumps({
                "category": "course",
                "course": "OPAR",
                "year": 2022,
                "quarter": 2,
                "week": 3,
                "lesson_number": 2,
                "difficulty": "introductory",
            }),
            metadata_quality=MetadataQuality.COMPLETE,
        ),
        FileRecord(
            file_path="/courses/opar/lesson03.txt",
            content_hash="opar3",
            filename="OPAR - Lesson 03 - Identity.txt",
            file_size=7000,
            metadata_json=json.dumps({
                "category": "course",
                "course": "OPAR",
                "year": 2023,
                "quarter": 3,
                "week": 5,
                "lesson_number": 3,
                "difficulty": "intermediate",
            }),
            metadata_quality=MetadataQuality.COMPLETE,
        ),
        # OPAR deleted file (should never appear)
        FileRecord(
            file_path="/courses/opar/deleted.txt",
            content_hash="opar_del",
            filename="OPAR - Deleted Lesson.txt",
            file_size=3000,
            metadata_json=json.dumps({
                "category": "course",
                "course": "OPAR",
                "year": 2020,
                "lesson_number": 99,
            }),
            metadata_quality=MetadataQuality.COMPLETE,
            status=FileStatus.LOCAL_DELETE,
        ),
        # ITOE course files (2)
        FileRecord(
            file_path="/courses/itoe/lesson01.txt",
            content_hash="itoe1",
            filename="ITOE - Lesson 01 - Concepts.txt",
            file_size=4500,
            metadata_json=json.dumps({
                "category": "course",
                "course": "ITOE",
                "year": 2022,
                "lesson_number": 1,
                "difficulty": "advanced",
            }),
            metadata_quality=MetadataQuality.COMPLETE,
        ),
        FileRecord(
            file_path="/courses/itoe/lesson02.txt",
            content_hash="itoe2",
            filename="ITOE - Lesson 02 - Definitions.txt",
            file_size=5500,
            metadata_json=json.dumps({
                "category": "course",
                "course": "ITOE",
                "year": 2023,
                "lesson_number": 2,
                "difficulty": "advanced",
            }),
            metadata_quality=MetadataQuality.COMPLETE,
        ),
        # MOTM files (2)
        FileRecord(
            file_path="/motm/jan2023.txt",
            content_hash="motm1",
            filename="MOTM - January 2023 - Free Will.txt",
            file_size=3000,
            metadata_json=json.dumps({
                "category": "motm",
                "year": 2023,
                "difficulty": "introductory",
            }),
            metadata_quality=MetadataQuality.PARTIAL,
        ),
        FileRecord(
            file_path="/motm/feb2023.txt",
            content_hash="motm2",
            filename="MOTM - February 2023 - Volition.txt",
            file_size=3500,
            metadata_json=json.dumps({
                "category": "motm",
                "year": 2023,
                "difficulty": "introductory",
            }),
            metadata_quality=MetadataQuality.PARTIAL,
        ),
        # Book files (2)
        FileRecord(
            file_path="/books/atlas.txt",
            content_hash="book1",
            filename="Atlas Shrugged - Chapter 1.txt",
            file_size=10000,
            metadata_json=json.dumps({
                "category": "book",
                "year": 1957,
                "difficulty": "introductory",
            }),
            metadata_quality=MetadataQuality.MINIMAL,
        ),
        FileRecord(
            file_path="/books/fountainhead.txt",
            content_hash="book2",
            filename="The Fountainhead - Chapter 1.txt",
            file_size=9000,
            metadata_json=json.dumps({
                "category": "book",
                "year": 1943,
                "difficulty": "introductory",
            }),
            metadata_quality=MetadataQuality.MINIMAL,
        ),
    ]

    db.upsert_files(records)
    yield db
    db.close()


class TestGetCategoriesWithCounts:
    """Tests for get_categories_with_counts."""

    def test_returns_correct_categories(self, browse_db: Database) -> None:
        """Returns 3 categories (course, motm, book) with correct counts.
        LOCAL_DELETE record excluded from course count."""
        categories = browse_db.get_categories_with_counts()
        cat_dict = dict(categories)

        assert "course" in cat_dict
        assert "motm" in cat_dict
        assert "book" in cat_dict
        assert len(cat_dict) == 3

    def test_correct_counts(self, browse_db: Database) -> None:
        """Course has 5 (3 OPAR + 2 ITOE), motm has 2, book has 2."""
        categories = browse_db.get_categories_with_counts()
        cat_dict = dict(categories)

        assert cat_dict["course"] == 5  # 3 OPAR + 2 ITOE (not the deleted one)
        assert cat_dict["motm"] == 2
        assert cat_dict["book"] == 2

    def test_excludes_deleted(self, browse_db: Database) -> None:
        """LOCAL_DELETE records are never counted."""
        categories = browse_db.get_categories_with_counts()
        total = sum(count for _, count in categories)
        # 9 active files (10 total - 1 deleted)
        assert total == 9

    def test_ordered_by_count_desc(self, browse_db: Database) -> None:
        """Categories are ordered by count descending."""
        categories = browse_db.get_categories_with_counts()
        counts = [count for _, count in categories]
        assert counts == sorted(counts, reverse=True)


class TestGetCoursesWithCounts:
    """Tests for get_courses_with_counts."""

    def test_returns_courses(self, browse_db: Database) -> None:
        """Returns 2 courses: ITOE and OPAR."""
        courses = browse_db.get_courses_with_counts()
        course_dict = dict(courses)

        assert len(course_dict) == 2
        assert "OPAR" in course_dict
        assert "ITOE" in course_dict

    def test_correct_counts(self, browse_db: Database) -> None:
        """OPAR=3 (excludes deleted), ITOE=2."""
        courses = browse_db.get_courses_with_counts()
        course_dict = dict(courses)

        assert course_dict["OPAR"] == 3
        assert course_dict["ITOE"] == 2

    def test_ordered_by_name(self, browse_db: Database) -> None:
        """Courses ordered alphabetically."""
        courses = browse_db.get_courses_with_counts()
        names = [name for name, _ in courses]
        assert names == sorted(names)


class TestGetFilesByCourse:
    """Tests for get_files_by_course."""

    def test_returns_all_course_files(self, browse_db: Database) -> None:
        """get_files_by_course('OPAR') returns 3 files."""
        files = browse_db.get_files_by_course("OPAR")
        assert len(files) == 3

    def test_returns_correct_structure(self, browse_db: Database) -> None:
        """Each result has filename, file_path, metadata keys."""
        files = browse_db.get_files_by_course("OPAR")
        for f in files:
            assert "filename" in f
            assert "file_path" in f
            assert "metadata" in f
            assert isinstance(f["metadata"], dict)

    def test_filtered_by_year(self, browse_db: Database) -> None:
        """Filtering by year returns subset."""
        files = browse_db.get_files_by_course("OPAR", year="2023")
        assert len(files) == 1
        assert files[0]["metadata"]["year"] == 2023

    def test_ordered_by_lesson_number(self, browse_db: Database) -> None:
        """Files ordered by lesson_number."""
        files = browse_db.get_files_by_course("OPAR")
        lesson_numbers = [f["metadata"]["lesson_number"] for f in files]
        assert lesson_numbers == sorted(lesson_numbers)

    def test_excludes_deleted(self, browse_db: Database) -> None:
        """Deleted OPAR file is not returned."""
        files = browse_db.get_files_by_course("OPAR")
        paths = {f["file_path"] for f in files}
        assert "/courses/opar/deleted.txt" not in paths

    def test_nonexistent_course(self, browse_db: Database) -> None:
        """Non-existent course returns empty list."""
        files = browse_db.get_files_by_course("NONEXISTENT")
        assert files == []


class TestGetItemsByCategory:
    """Tests for get_items_by_category."""

    def test_returns_motm_files(self, browse_db: Database) -> None:
        """get_items_by_category('motm') returns 2 files."""
        files = browse_db.get_items_by_category("motm")
        assert len(files) == 2

    def test_returns_book_files(self, browse_db: Database) -> None:
        """get_items_by_category('book') returns 2 files."""
        files = browse_db.get_items_by_category("book")
        assert len(files) == 2

    def test_correct_structure(self, browse_db: Database) -> None:
        """Each result has filename, file_path, metadata."""
        files = browse_db.get_items_by_category("motm")
        for f in files:
            assert "filename" in f
            assert "file_path" in f
            assert "metadata" in f

    def test_ordered_by_filename(self, browse_db: Database) -> None:
        """Results ordered by filename."""
        files = browse_db.get_items_by_category("motm")
        filenames = [f["filename"] for f in files]
        assert filenames == sorted(filenames)


class TestFilterFilesByMetadata:
    """Tests for filter_files_by_metadata."""

    def test_filter_exact_course(self, browse_db: Database) -> None:
        """filter_files_by_metadata({'course': 'OPAR'}) returns 3."""
        results = browse_db.filter_files_by_metadata({"course": "OPAR"})
        assert len(results) == 3

    def test_filter_numeric_year(self, browse_db: Database) -> None:
        """filter_files_by_metadata({'year': '2023'}) returns correct count."""
        results = browse_db.filter_files_by_metadata({"year": "2023"})
        # 2023: OPAR lesson03, ITOE lesson02, MOTM jan, MOTM feb = 4
        assert len(results) == 4

    def test_filter_comparison_gte(self, browse_db: Database) -> None:
        """filter_files_by_metadata({'year': '>=2022'}) returns correct count."""
        results = browse_db.filter_files_by_metadata({"year": ">=2022"})
        # 2022: OPAR lesson02, ITOE lesson01 = 2
        # 2023: OPAR lesson03, ITOE lesson02, MOTM jan, MOTM feb = 4
        # total = 6
        assert len(results) == 6

    def test_filter_comparison_gt(self, browse_db: Database) -> None:
        """Greater-than comparison works."""
        results = browse_db.filter_files_by_metadata({"year": ">2022"})
        # Only 2023 files: OPAR lesson03, ITOE lesson02, MOTM jan, MOTM feb = 4
        assert len(results) == 4

    def test_filter_comparison_lt(self, browse_db: Database) -> None:
        """Less-than comparison works."""
        results = browse_db.filter_files_by_metadata({"year": "<1957"})
        # Only 1943 book: The Fountainhead
        assert len(results) == 1

    def test_filter_combined(self, browse_db: Database) -> None:
        """Combined filters return intersection."""
        results = browse_db.filter_files_by_metadata({"course": "OPAR", "year": "2023"})
        assert len(results) == 1
        assert results[0]["metadata"]["course"] == "OPAR"
        assert results[0]["metadata"]["year"] == 2023

    def test_filter_invalid_field(self, browse_db: Database) -> None:
        """Unknown field raises ValueError with helpful message."""
        with pytest.raises(ValueError, match="Unknown filter field: bogus"):
            browse_db.filter_files_by_metadata({"bogus": "val"})

    def test_filter_invalid_field_lists_valid(self, browse_db: Database) -> None:
        """Error message includes valid field names."""
        with pytest.raises(ValueError, match="Valid:"):
            browse_db.filter_files_by_metadata({"nope": "val"})

    def test_filter_excludes_deleted(self, browse_db: Database) -> None:
        """LOCAL_DELETE records never appear in filter results."""
        # Even filtering for the deleted year should not return it
        results = browse_db.filter_files_by_metadata({"year": "2020"})
        assert len(results) == 0

    def test_filter_limit(self, browse_db: Database) -> None:
        """Limit parameter restricts result count."""
        results = browse_db.filter_files_by_metadata({"category": "course"}, limit=2)
        assert len(results) == 2

    def test_filter_difficulty(self, browse_db: Database) -> None:
        """Can filter by difficulty field."""
        results = browse_db.filter_files_by_metadata({"difficulty": "advanced"})
        assert len(results) == 2
        for r in results:
            assert r["metadata"]["difficulty"] == "advanced"
