"""Test file generation with edge-case display_names for round-trip testing.

Generates 14 small .txt test files with deliberately tricky display_names
to stress-test whether the Gemini API normalizes display_name values.
"""

from __future__ import annotations

import os
from typing import Any

# Filler text for generating files of specific sizes
_FILLER_PARAGRAPH = (
    "The concept of objectivity in epistemology requires that knowledge be based "
    "on evidence derived from reality through a process of reason. This principle "
    "applies equally to the evaluation of philosophical arguments and to the "
    "assessment of empirical data gathered through systematic observation. "
    "A proper epistemology must identify the means by which man acquires knowledge "
    "and must validate those means by reference to the facts of reality.\n\n"
)

# Each entry: (display_name, category, target_size_bytes)
_TEST_CASES: list[tuple[str, str, int]] = [
    # 4 basic cases (~1KB each)
    ("Simple Test Name", "basic", 1024),
    ("lowercase_only_name", "basic", 1024),
    ("UPPERCASE_ONLY_NAME", "basic", 1024),
    ("MiXeD CaSe NaMe", "basic", 1024),
    # 4 special character cases (~10KB each)
    ("Name With (Parentheses)", "special", 10240),
    ("Name-With-Dashes-And-More", "special", 10240),
    ("Philosophy Q&A Session", "special", 10240),
    ("Introduction Ch.1 Overview", "special", 10240),
    # 2 whitespace edge cases (~50KB each)
    ("  Leading Spaces Name", "whitespace", 51200),
    ("Trailing Spaces Name  ", "whitespace", 51200),
    # 2 realistic library filenames (~50KB each)
    ("Ayn Rand - Atlas Shrugged (1957)", "realistic", 51200),
    ("OCON 2023 - Harry Binswanger - Q&A", "realistic", 51200),
    # 1 long name (~100KB)
    ("A" * 500, "long", 102400),
    # 1 internal multiple spaces (~100KB)
    ("Multiple   Internal   Spaces", "multiple_spaces", 102400),
]


def _generate_content(target_size: int) -> str:
    """Generate text content of approximately the target size in bytes."""
    paragraph_size = len(_FILLER_PARAGRAPH.encode("utf-8"))
    repetitions = max(1, target_size // paragraph_size)
    content = _FILLER_PARAGRAPH * repetitions
    # Trim or pad to approximate target size
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > target_size:
        content = content_bytes[:target_size].decode("utf-8", errors="ignore")
    return content


def _size_bucket(size_bytes: int) -> str:
    """Classify a file size into a bucket label."""
    if size_bytes <= 2048:
        return "1KB"
    elif size_bytes <= 20480:
        return "10KB"
    elif size_bytes <= 75000:
        return "50KB"
    else:
        return "100KB"


def create_test_corpus(base_dir: str) -> list[dict[str, Any]]:
    """Generate 14 test files with tricky display_names.

    Args:
        base_dir: Directory to write test files into.

    Returns:
        List of dicts with keys: local_path, display_name, size_bytes, index,
        category, size_bucket.
    """
    os.makedirs(base_dir, exist_ok=True)
    results = []

    for idx, (display_name, category, target_size) in enumerate(_TEST_CASES):
        # Sanitized local filename (avoid filesystem issues)
        local_filename = f"test_file_{idx:02d}.txt"
        local_path = os.path.join(base_dir, local_filename)

        content = _generate_content(target_size)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(content)

        actual_size = os.path.getsize(local_path)
        results.append(
            {
                "local_path": local_path,
                "display_name": display_name,
                "size_bytes": actual_size,
                "index": idx,
                "category": category,
                "size_bucket": _size_bucket(actual_size),
            }
        )

    return results
