#!/usr/bin/env python3
"""
Library Scanner - Phase 1: Scan & Metadata Extraction

This script recursively scans the Objectivism Library folder and extracts
metadata from the folder structure and filenames.

Usage:
    python 01_scan_library.py --verbose
    python 01_scan_library.py --config ../config/library_config.json --output ../data/catalog.json
"""

import os
import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import hashlib

class LibraryScanner:
    """Scans library folder and extracts metadata from structure"""

    def __init__(self, library_root: str, config: Dict[str, Any] = None):
        self.library_root = Path(library_root)
        self.config = config or {}
        self.excluded_patterns = self.config.get('excluded_patterns', ['.claude', '.DS_Store', '.git'])
        self.file_extensions = self.config.get('file_extensions', ['.txt'])
        self.catalog = {
            'metadata': {
                'scan_timestamp': datetime.now().isoformat(),
                'library_root': str(self.library_root),
                'total_files': 0,
                'scanner_version': '1.0.0'
            },
            'files': []
        }

    def should_exclude(self, path: Path) -> bool:
        """Check if path matches exclusion patterns"""
        path_str = str(path)
        for pattern in self.excluded_patterns:
            if pattern in path_str:
                return True
        return False

    def extract_metadata_from_path(self, file_path: Path) -> Dict[str, Any]:
        """Extract metadata from file path and name"""
        rel_path = file_path.relative_to(self.library_root)
        parts = rel_path.parts

        metadata = {
            'core': {
                'source_path': str(rel_path),
                'filename': file_path.name,
                'file_size_bytes': file_path.stat().st_size,
                'file_modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                'content_hash': self.compute_hash(file_path)
            },
            'classification': {
                'primary_category': self.determine_category(parts),
                'content_type': self.determine_content_type(file_path.name),
                'format': 'Transcript'
            },
            'intellectual': {
                'title': self.extract_title(file_path.name),
                'topics': [],
                'subtopics': [],
                'key_concepts': []
            },
            'instructional': {
                'instructor': self.infer_instructor(parts, file_path.name),
                'difficulty_level': self.infer_difficulty(parts, file_path.name),
                'prerequisites': [],
                'builds_on': [],
                'prepares_for': []
            },
            'pedagogical_structure': {},
            'temporal': {},
            'relational': {},
            'content_characteristics': {}
        }

        # Extract category-specific metadata
        if parts[0] == 'Courses':
            self.extract_course_metadata(parts, file_path.name, metadata)
        elif parts[0] == 'Books':
            self.extract_book_metadata(parts, file_path.name, metadata)
        elif parts[0] == 'MOTM':
            self.extract_motm_metadata(parts, file_path.name, metadata)
        elif parts[0] == 'Peikoff Podcast':
            self.extract_podcast_metadata(parts, file_path.name, metadata)

        return metadata

    def compute_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file for deduplication"""
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            print(f"Warning: Could not hash {file_path}: {e}")
            return ""

    def determine_category(self, parts: tuple) -> str:
        """Determine primary category from path"""
        category_map = {
            'Courses': 'Course',
            'Books': 'Book',
            'MOTM': 'MOTM',
            'Peikoff Podcast': 'Podcast',
            'Ayn Rand Conf Austin 2025': 'Conference',
            'HBTV': 'HBTV',
            'Ayn Rand Institute': 'ARI_Content'
        }
        return category_map.get(parts[0], 'Other')

    def determine_content_type(self, filename: str) -> str:
        """Infer content type from filename"""
        filename_lower = filename.lower()
        if 'office hour' in filename_lower or 'office-hour' in filename_lower:
            return 'OfficeHour'
        elif 'q&a' in filename_lower or 'q and a' in filename_lower or 'qa' in filename_lower:
            return 'QA'
        elif 'discussion' in filename_lower:
            return 'Discussion'
        elif 'interview' in filename_lower:
            return 'Interview'
        elif 'chapter' in filename_lower:
            return 'BookChapter'
        else:
            return 'Lecture'

    def extract_title(self, filename: str) -> str:
        """Extract human-readable title from filename"""
        # Remove extension
        title = filename.replace('.txt', '')

        # Common patterns to clean
        # Pattern: "Course Name - Year X - QX - Week X - Title"
        patterns = [
            r'^.*?-\s*Year\s*\d+\s*-\s*Q\d+\s*-\s*Week\s*\d+\s*-\s*(.+)$',  # Course with year/quarter/week
            r'^.*?-\s*Lesson\s*\d+\s*-\s*(.+)$',  # Course with lesson number
            r'^.*?-\s*Class\s*\d+\s*-\s*(.+)$',   # Course with class number
            r'^MOTM_\d{4}-\d{2}-\d{2}_(.+)$',     # MOTM pattern
        ]

        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                return match.group(1).strip()

        # If no pattern matches, return cleaned filename
        return title.strip()

    def infer_instructor(self, parts: tuple, filename: str) -> str:
        """Infer instructor from path or filename"""
        filename_lower = filename.lower()
        path_str = '/'.join(parts).lower()

        # Known instructors
        if 'peikoff' in path_str or 'peikoff' in filename_lower:
            return 'Leonard Peikoff'
        elif 'binswanger' in path_str or 'binswanger' in filename_lower:
            return 'Harry Binswanger'
        elif 'ghate' in path_str or 'ghate' in filename_lower:
            return 'Onkar Ghate'
        elif 'salsman' in path_str or 'salsman' in filename_lower:
            return 'Richard Salsman'

        # Default for certain categories
        if parts[0] == 'MOTM':
            return 'Harry Binswanger'  # MOTM host
        elif parts[0] == 'Peikoff Podcast':
            return 'Leonard Peikoff'

        return 'Unknown'

    def infer_difficulty(self, parts: tuple, filename: str) -> str:
        """Infer difficulty level from structure and naming"""
        path_str = '/'.join(parts).lower()

        # Check for explicit indicators
        if 'foundations' in path_str or 'introduction' in path_str:
            return 'Foundations'
        elif 'advanced' in path_str:
            return 'Advanced'
        elif 'expert' in path_str or 'graduate' in path_str:
            return 'Expert'

        # Infer from course structure
        if len(parts) >= 3 and parts[1]:  # Has course name
            if 'year1' in path_str.lower():
                return 'Foundations'
            elif 'year2' in path_str.lower():
                return 'Intermediate'
            elif 'year3' in path_str.lower() or 'year4' in path_str.lower():
                return 'Advanced'

        return 'Intermediate'  # Default

    def extract_course_metadata(self, parts: tuple, filename: str, metadata: Dict[str, Any]):
        """Extract course-specific metadata"""
        if len(parts) < 2:
            return

        course_name = parts[1]
        metadata['pedagogical_structure']['course_name'] = course_name
        metadata['content_characteristics']['primary_branch'] = self.infer_philosophy_branch(course_name, filename)

        # Check for Year/Quarter/Week structure
        for i, part in enumerate(parts):
            part_lower = part.lower()

            # Year
            year_match = re.match(r'year(\d+)', part_lower)
            if year_match:
                metadata['pedagogical_structure']['course_sequence'] = metadata['pedagogical_structure'].get('course_sequence', {})
                metadata['pedagogical_structure']['course_sequence']['year'] = f"Year{year_match.group(1)}"

                # Check next part for Quarter
                if i + 1 < len(parts):
                    next_part = parts[i + 1].lower()
                    quarter_match = re.match(r'q(\d+)', next_part)
                    if quarter_match:
                        metadata['pedagogical_structure']['course_sequence']['quarter'] = f"Q{quarter_match.group(1)}"

        # Check for Week in filename
        week_match = re.search(r'Week\s*(\d+)', filename, re.IGNORECASE)
        if week_match:
            if 'course_sequence' not in metadata['pedagogical_structure']:
                metadata['pedagogical_structure']['course_sequence'] = {}
            metadata['pedagogical_structure']['course_sequence']['week'] = f"Week{week_match.group(1)}"

        # Check for Class/Lesson number
        class_match = re.search(r'(?:Class|Lesson)\s*(\d+)', filename, re.IGNORECASE)
        if class_match:
            if 'course_sequence' not in metadata['pedagogical_structure']:
                metadata['pedagogical_structure']['course_sequence'] = {}
            metadata['pedagogical_structure']['course_sequence']['class_number'] = int(class_match.group(1))

    def extract_book_metadata(self, parts: tuple, filename: str, metadata: Dict[str, Any]):
        """Extract book-specific metadata"""
        if len(parts) >= 2:
            book_title = parts[1]
            metadata['book_metadata'] = {
                'book_title': book_title,
                'is_ayn_rand_authored': 'ayn rand' in book_title.lower(),
                'is_peikoff_authored': 'peikoff' in book_title.lower()
            }

            # Check for chapter
            chapter_match = re.search(r'Chapter\s*(\d+)', filename, re.IGNORECASE)
            if chapter_match:
                metadata['bibliographic'] = {
                    'chapter_number': int(chapter_match.group(1))
                }

    def extract_motm_metadata(self, parts: tuple, filename: str, metadata: Dict[str, Any]):
        """Extract MOTM-specific metadata"""
        # Pattern: MOTM_YYYY-MM-DD_Title.txt
        date_match = re.search(r'MOTM_(\d{4})-(\d{2})-(\d{2})', filename)
        if date_match:
            year, month, day = date_match.groups()
            metadata['motm_metadata'] = {
                'session_date': f"{year}-{month}-{day}",
                'host': 'Harry Binswanger',
                'format': 'Discussion'
            }
            metadata['temporal']['recording_date'] = f"{year}-{month}-{day}"
            metadata['temporal']['recording_year'] = int(year)

    def extract_podcast_metadata(self, parts: tuple, filename: str, metadata: Dict[str, Any]):
        """Extract podcast-specific metadata"""
        metadata['podcast_metadata'] = {
            'podcast_name': 'Leonard Peikoff Podcast',
            'podcast_host': 'Leonard Peikoff'
        }

        # Try to extract episode number
        ep_match = re.search(r'(?:Episode|Ep)\s*(\d+)', filename, re.IGNORECASE)
        if ep_match:
            metadata['podcast_metadata']['episode_number'] = int(ep_match.group(1))

    def infer_philosophy_branch(self, course_name: str, filename: str) -> str:
        """Infer primary philosophy branch from course name and filename"""
        combined = (course_name + ' ' + filename).lower()

        if any(term in combined for term in ['ethics', 'virtue', 'values', 'moral', 'egoism']):
            return 'Ethics'
        elif any(term in combined for term in ['epistemology', 'knowledge', 'itoe', 'concepts', 'logic', 'certainty']):
            return 'Epistemology'
        elif any(term in combined for term in ['metaphysics', 'existence', 'identity', 'causality', 'reality']):
            return 'Metaphysics'
        elif any(term in combined for term in ['politics', 'government', 'rights', 'capitalism', 'freedom']):
            return 'Politics'
        elif any(term in combined for term in ['aesthetics', 'art', 'literature', 'romantic']):
            return 'Aesthetics'
        elif any(term in combined for term in ['history', 'philosophy', 'historical']):
            return 'History'
        else:
            return 'Applied'

    def scan(self, verbose: bool = False) -> Dict[str, Any]:
        """Scan entire library and build catalog"""
        print(f"Scanning library: {self.library_root}")
        print(f"Excluded patterns: {self.excluded_patterns}")
        print(f"File extensions: {self.file_extensions}")
        print()

        file_count = 0
        for ext in self.file_extensions:
            for file_path in self.library_root.rglob(f"*{ext}"):
                if self.should_exclude(file_path):
                    if verbose:
                        print(f"Skipping (excluded): {file_path.relative_to(self.library_root)}")
                    continue

                try:
                    metadata = self.extract_metadata_from_path(file_path)
                    self.catalog['files'].append(metadata)
                    file_count += 1

                    if verbose:
                        print(f"[{file_count}] {metadata['intellectual']['title']}")
                        print(f"     Category: {metadata['classification']['primary_category']}")
                        if 'course_name' in metadata.get('pedagogical_structure', {}):
                            print(f"     Course: {metadata['pedagogical_structure']['course_name']}")
                        print()
                    elif file_count % 50 == 0:
                        print(f"Processed {file_count} files...")

                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    continue

        self.catalog['metadata']['total_files'] = file_count
        print(f"\nScan complete! Processed {file_count} files.")

        # Print statistics
        self.print_statistics()

        return self.catalog

    def print_statistics(self):
        """Print catalog statistics"""
        print("\n" + "="*60)
        print("CATALOG STATISTICS")
        print("="*60)

        # Count by category
        category_counts = {}
        for file in self.catalog['files']:
            category = file['classification']['primary_category']
            category_counts[category] = category_counts.get(category, 0) + 1

        print("\nFiles by Category:")
        for category, count in sorted(category_counts.items(), key=lambda x: -x[1]):
            print(f"  {category:20s}: {count:4d}")

        # Count courses
        courses = set()
        for file in self.catalog['files']:
            if 'course_name' in file.get('pedagogical_structure', {}):
                courses.add(file['pedagogical_structure']['course_name'])

        print(f"\nTotal Unique Courses: {len(courses)}")

        # Count by difficulty
        difficulty_counts = {}
        for file in self.catalog['files']:
            difficulty = file['instructional'].get('difficulty_level', 'Unknown')
            difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1

        print("\nFiles by Difficulty:")
        for difficulty, count in sorted(difficulty_counts.items()):
            print(f"  {difficulty:20s}: {count:4d}")

        print()

    def save_catalog(self, output_path: str):
        """Save catalog to JSON file"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.catalog, f, indent=2, ensure_ascii=False)

        print(f"Catalog saved to: {output_path}")
        print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")


def main():
    parser = argparse.ArgumentParser(description='Scan Objectivism Library and extract metadata')
    parser.add_argument('--library-root', type=str,
                       default='/Volumes/U32 Shadow/Objectivism Library',
                       help='Path to library root folder')
    parser.add_argument('--config', type=str,
                       help='Path to config JSON file')
    parser.add_argument('--output', type=str,
                       default='../data/library_catalog.json',
                       help='Output catalog file path')
    parser.add_argument('--verbose', action='store_true',
                       help='Print detailed progress')

    args = parser.parse_args()

    # Load config if provided
    config = {}
    if args.config:
        with open(args.config, 'r') as f:
            config = json.load(f)

    # Create scanner and run
    scanner = LibraryScanner(args.library_root, config)
    catalog = scanner.scan(verbose=args.verbose)
    scanner.save_catalog(args.output)

    print("\nDone! Next step: python 02_upload_to_gemini.py")


if __name__ == '__main__':
    main()
