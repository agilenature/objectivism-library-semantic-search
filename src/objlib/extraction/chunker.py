"""Adaptive context window management for transcripts of varying length.

Handles files from 2KB to 7MB using full-text, head-tail windowing,
or windowed sampling strategies based on estimated token count.

Token estimation uses a simple heuristic (4 chars per token for English).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Approximate characters per token for English text
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count using a simple character-based heuristic.

    Uses ~4 characters per token as an approximation for English text.

    Args:
        text: Input text string.

    Returns:
        Estimated token count (always >= 1 for non-empty text).
    """
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _tokens_to_chars(tokens: int) -> int:
    """Convert token count back to approximate character count.

    Args:
        tokens: Number of tokens.

    Returns:
        Approximate character count.
    """
    return tokens * _CHARS_PER_TOKEN


def prepare_transcript(file_path: str, max_tokens: int = 18000) -> str:
    """Read and prepare a transcript for API submission.

    Reads the file from disk, estimates token count, and applies
    appropriate chunking strategy:

    - Full text: if <= max_tokens
    - Head-tail: if <= max_tokens * 1.5 (slightly over)
      Extracts first 70% and last 30% of allowed tokens.
    - Windowed sampling: if > max_tokens * 1.5 (very long)
      Extracts head (3000 tokens), 3 evenly-spaced middle windows
      (600 tokens each), and tail (3000 tokens).

    Truncated content includes a note instructing the model to lower
    confidence if context seems insufficient.

    Args:
        file_path: Path to the transcript file on disk.
        max_tokens: Maximum token budget (default 18000).

    Returns:
        Prepared transcript text, potentially truncated with markers.

    Raises:
        FileNotFoundError: If file_path does not exist.
    """
    path = Path(file_path)

    # Read with UTF-8 fallback to latin-1
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        logger.warning("UTF-8 decode failed for %s, falling back to latin-1", file_path)
        text = path.read_text(encoding="latin-1")

    tokens = estimate_tokens(text)

    if tokens <= max_tokens:
        # Full text fits within budget
        return text

    truncation_note = (
        "\n\n[NOTE: Content was excerpted. Base metadata on provided "
        "text only. Lower confidence_score if context seems insufficient.]"
    )

    if tokens <= max_tokens * 1.5:
        # Head-tail strategy: first 70%, last 30%
        head_chars = _tokens_to_chars(int(max_tokens * 0.70))
        tail_chars = _tokens_to_chars(int(max_tokens * 0.30))

        head = text[:head_chars]
        tail = text[-tail_chars:]

        logger.info(
            "Head-tail chunking for %s: %d tokens -> %d head + %d tail",
            file_path, tokens, int(max_tokens * 0.70), int(max_tokens * 0.30),
        )

        return (
            f"[START]\n{head}\n\n"
            f"[...CONTENT TRUNCATED...]\n\n"
            f"[END]\n{tail}"
            f"{truncation_note}"
        )

    # Windowed sampling for very long files
    head_tokens = 3000
    tail_tokens = 3000
    window_tokens = 600
    num_windows = 3

    head_chars = _tokens_to_chars(head_tokens)
    tail_chars = _tokens_to_chars(tail_tokens)
    window_chars = _tokens_to_chars(window_tokens)

    head = text[:head_chars]
    tail = text[-tail_chars:]

    # Calculate evenly-spaced window positions in the middle section
    middle_start = head_chars
    middle_end = len(text) - tail_chars
    middle_length = middle_end - middle_start

    windows = []
    if middle_length > 0 and num_windows > 0:
        spacing = middle_length // (num_windows + 1)
        for i in range(1, num_windows + 1):
            start = middle_start + (spacing * i)
            end = min(start + window_chars, middle_end)
            windows.append(text[start:end])

    logger.info(
        "Windowed sampling for %s: %d tokens -> head(%d) + %d windows(%d each) + tail(%d)",
        file_path, tokens, head_tokens, num_windows, window_tokens, tail_tokens,
    )

    parts = [f"[START]\n{head}"]
    for i, window in enumerate(windows, 1):
        parts.append(f"[EXCERPT {i}]\n{window}")
    parts.append(f"[END]\n{tail}")

    return "\n\n".join(parts) + truncation_note
