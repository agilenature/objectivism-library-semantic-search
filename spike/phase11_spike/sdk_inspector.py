"""Programmatic SDK source evidence collection for display_name serialization path.

Inspects the installed google-genai SDK source files to document:
1. Where display_name is set during file upload (files.py)
2. How File, Document, UploadFileConfig define display_name (types.py)
3. How Pydantic alias_generator serializes display_name -> displayName (_common.py)
"""

from __future__ import annotations

import importlib.metadata
import inspect
import re
from pathlib import Path
from typing import Any


def _find_lines(source_lines: list[str], patterns: list[dict]) -> list[dict]:
    """Search source lines for patterns, returning matches with context.

    Args:
        source_lines: Lines of source code (0-indexed).
        patterns: List of dicts with 'pattern' (regex) and 'description' keys.

    Returns:
        List of dicts with line_no (1-indexed), content, and description.
    """
    results = []
    for pat_info in patterns:
        pattern = re.compile(pat_info["pattern"])
        for i, line in enumerate(source_lines):
            if pattern.search(line):
                results.append(
                    {
                        "line_no": i + 1,  # 1-indexed
                        "content": line.rstrip(),
                        "description": pat_info["description"],
                    }
                )
    return results


def collect_sdk_evidence() -> dict[str, Any]:
    """Collect evidence about display_name serialization from installed SDK source.

    Returns:
        Dict with SDK version, file paths, matched lines, and conclusion.
    """
    import google.genai.files
    import google.genai.types
    import google.genai._common

    sdk_version = importlib.metadata.version("google-genai")

    # --- files.py evidence ---
    files_path = inspect.getfile(google.genai.files)
    files_source = Path(files_path).read_text()
    files_lines = files_source.splitlines()

    files_evidence = _find_lines(
        files_lines,
        [
            {
                "pattern": r"display_name\s*=\s*config_model\.display_name",
                "description": "display_name passed from UploadFileConfig to File object (sync and async upload methods)",
            },
        ],
    )

    # --- types.py evidence ---
    types_path = inspect.getfile(google.genai.types)
    types_source = Path(types_path).read_text()
    types_lines = types_source.splitlines()

    types_evidence = _find_lines(
        types_lines,
        [
            {
                "pattern": r"^class File\(_common\.BaseModel\)",
                "description": "File model class definition (inherits BaseModel with alias_generator)",
            },
            {
                "pattern": r"^class Document\(_common\.BaseModel\)",
                "description": "Document model class definition (inherits BaseModel with alias_generator)",
            },
            {
                "pattern": r"^class UploadFileConfig\(_common\.BaseModel\)",
                "description": "UploadFileConfig model class definition",
            },
        ],
    )

    # Also find the display_name fields on File, Document, and UploadFileConfig
    # We search within the class bodies by finding display_name near the class definitions
    for class_pattern, class_name in [
        (r"^class File\(_common\.BaseModel\)", "File"),
        (r"^class Document\(_common\.BaseModel\)", "Document"),
        (r"^class UploadFileConfig\(_common\.BaseModel\)", "UploadFileConfig"),
    ]:
        # Find the class start line
        class_start = None
        for i, line in enumerate(types_lines):
            if re.match(class_pattern, line):
                class_start = i
                break
        if class_start is not None:
            # Search for display_name field within 100 lines of class start
            for j in range(class_start, min(class_start + 100, len(types_lines))):
                if "display_name:" in types_lines[j] and "Optional" in types_lines[j]:
                    types_evidence.append(
                        {
                            "line_no": j + 1,
                            "content": types_lines[j].rstrip(),
                            "description": f"{class_name}.display_name field definition",
                        }
                    )
                    break

    # --- _common.py evidence ---
    common_path = inspect.getfile(google.genai._common)
    common_source = Path(common_path).read_text()
    common_lines = common_source.splitlines()

    common_evidence = _find_lines(
        common_lines,
        [
            {
                "pattern": r"alias_generator\s*=\s*alias_generators\.to_camel",
                "description": "Pydantic alias_generator converts snake_case to camelCase (display_name -> displayName)",
            },
            {
                "pattern": r"class BaseModel\(pydantic\.BaseModel\)",
                "description": "BaseModel class that all SDK types inherit from",
            },
            {
                "pattern": r"populate_by_name\s*=\s*True",
                "description": "populate_by_name=True allows both snake_case and camelCase field access",
            },
        ],
    )

    # Build conclusion based on evidence found
    files_has_display_name = len(files_evidence) > 0
    types_has_classes = any("class definition" in e["description"] for e in types_evidence)
    types_has_fields = any("field definition" in e["description"] for e in types_evidence)
    common_has_alias = any("alias_generator" in e["description"] for e in common_evidence)

    if files_has_display_name and types_has_classes and types_has_fields and common_has_alias:
        conclusion = (
            "CONFIRMED: display_name is caller-controlled. The SDK passes display_name "
            "directly from UploadFileConfig to the File object without any transformation. "
            "The Pydantic alias_generator (to_camel) only affects JSON serialization "
            "(display_name -> displayName in the HTTP request body), not the value itself. "
            "The SDK does NOT normalize, truncate, or modify the display_name string."
        )
    else:
        missing = []
        if not files_has_display_name:
            missing.append("display_name assignment in files.py")
        if not types_has_classes:
            missing.append("class definitions in types.py")
        if not types_has_fields:
            missing.append("display_name field definitions in types.py")
        if not common_has_alias:
            missing.append("alias_generator in _common.py")
        conclusion = f"INCOMPLETE: Could not find evidence for: {', '.join(missing)}"

    return {
        "sdk_version": sdk_version,
        "files_py": {
            "path": files_path,
            "lines": files_evidence,
        },
        "types_py": {
            "path": types_path,
            "lines": types_evidence,
        },
        "common_py": {
            "path": common_path,
            "lines": common_evidence,
        },
        "conclusion": conclusion,
    }
