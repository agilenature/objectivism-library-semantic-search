"""Content preparation for enriched Gemini uploads.

Creates temporary files with Tier 4 AI analysis prepended to the
original file text. This ensures Gemini embeddings capture both the
AI-generated philosophical context and the raw transcript content.

The caller is responsible for cleaning up temporary files via
:func:`cleanup_temp_file` or ``os.unlink()``.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def prepare_enriched_content(
    original_file_path: str,
    ai_metadata: dict,
) -> str | None:
    """Create a temporary file with AI analysis prepended to original text.

    The header format is::

        [AI Analysis]
        Category: {category} | Difficulty: {difficulty}

        Summary: {tier4_summary}

        Key Arguments:
        - {argument_1}
        - {argument_2}

        Philosophical Positions:
        - {position_1}

        [Original Content]
        {original file text}

    If ALL Tier 4 fields are empty (no summary, no arguments, no
    positions), returns ``None`` indicating no content injection is
    needed and the original file should be uploaded as-is.

    Args:
        original_file_path: Path to the original .txt file.
        ai_metadata: Parsed JSON from file_metadata_ai.metadata_json.

    Returns:
        Path to the temporary file (caller must clean up), or ``None``
        if no Tier 4 content is available.
    """
    semantic = ai_metadata.get("semantic_description", {})
    summary = semantic.get("summary", "")
    key_arguments = semantic.get("key_arguments", [])
    positions = semantic.get("philosophical_positions", [])

    # If all Tier 4 fields are empty, skip content injection
    if not summary and not key_arguments and not positions:
        return None

    # Build header
    header_parts = ["[AI Analysis]"]
    header_parts.append(
        f"Category: {ai_metadata.get('category', 'unknown')} | "
        f"Difficulty: {ai_metadata.get('difficulty', 'unknown')}"
    )
    header_parts.append("")

    if summary:
        header_parts.append(f"Summary: {summary}")
        header_parts.append("")

    if key_arguments:
        header_parts.append("Key Arguments:")
        for arg in key_arguments:
            header_parts.append(f"- {arg}")
        header_parts.append("")

    if positions:
        header_parts.append("Philosophical Positions:")
        for pos in positions:
            header_parts.append(f"- {pos}")
        header_parts.append("")

    header_parts.append("[Original Content]")
    header = "\n".join(header_parts) + "\n"

    # Read original file and create temp file with prepended content
    original_text = Path(original_file_path).read_text(encoding="utf-8")

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(header)
        tmp.write(original_text)
        tmp.close()
    except Exception:
        tmp.close()
        cleanup_temp_file(tmp.name)
        raise

    logger.debug(
        "Prepared enriched content: %s -> %s (%d bytes header)",
        original_file_path,
        tmp.name,
        len(header.encode("utf-8")),
    )
    return tmp.name


def cleanup_temp_file(path: str | None) -> None:
    """Safely remove a temporary file.

    Handles ``None`` paths and missing files gracefully.

    Args:
        path: Path to the temporary file, or ``None``.
    """
    if path is None:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Failed to clean up temp file: %s", path, exc_info=True)
