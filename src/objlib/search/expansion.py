"""Query expansion engine for Objectivist philosophy terminology.

Loads a curated glossary (synonyms.yml) and expands search queries
by appending relevant synonyms for matched terms. This improves
recall for Gemini File Search by bridging terminology gaps.

Example:
    >>> from objlib.search.expansion import expand_query
    >>> expanded, applied = expand_query("What is egoism?")
    >>> print(expanded)
    'What is egoism? egoism rational self-interest selfishness'
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

# Module-level glossary cache
_glossary_cache: dict[str, list[str]] | None = None

DEFAULT_GLOSSARY_PATH = Path(__file__).parent / "synonyms.yml"


def load_glossary(path: Path | None = None) -> dict[str, list[str]]:
    """Load the Objectivist terminology glossary from YAML.

    Caches the result at module level for subsequent calls.

    Args:
        path: Path to synonyms.yml. Defaults to the file
              co-located with this module.

    Returns:
        Dict mapping lowercase term -> list of synonym strings.
    """
    global _glossary_cache

    glossary_path = path or DEFAULT_GLOSSARY_PATH

    # Return cache only if using default path
    if _glossary_cache is not None and path is None:
        return _glossary_cache

    with open(glossary_path) as f:
        raw = yaml.safe_load(f)

    # Normalize keys to lowercase
    glossary: dict[str, list[str]] = {}
    for term, synonyms in raw.items():
        glossary[str(term).lower()] = [str(s) for s in synonyms]

    # Cache only for default path
    if path is None:
        _glossary_cache = glossary

    return glossary


def expand_query(
    query: str,
    glossary: dict[str, list[str]] | None = None,
    max_synonyms: int = 2,
) -> tuple[str, list[str]]:
    """Expand a query string with synonyms from the glossary.

    Matches terms case-insensitively, checking multi-word phrases
    first (longest first) to avoid partial matches. For each match,
    the original term is boosted (appears twice) and top synonyms
    are appended.

    Args:
        query: Original search query.
        glossary: Pre-loaded glossary dict, or None to auto-load.
        max_synonyms: Maximum synonyms to add per matched term.

    Returns:
        Tuple of (expanded_query_string, list_of_expansion_descriptions).
        If no terms match, returns (original_query, []).

    Example:
        >>> expand_query("What is egoism?")
        ('What is egoism? egoism rational self-interest selfishness',
         ['egoism -> rational self-interest, selfishness'])
    """
    if glossary is None:
        glossary = load_glossary()

    query_lower = query.lower()
    expansions: list[str] = []
    applied: list[str] = []
    matched_spans: list[tuple[int, int]] = []

    # Sort terms by length descending to match longer phrases first
    sorted_terms = sorted(glossary.keys(), key=len, reverse=True)

    for term in sorted_terms:
        # Build word-boundary pattern for the term
        pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        match = pattern.search(query_lower)
        if match is None:
            continue

        # Check if this match overlaps with an already-matched span
        start, end = match.start(), match.end()
        overlaps = False
        for ms, me in matched_spans:
            if start < me and end > ms:
                overlaps = True
                break
        if overlaps:
            continue

        matched_spans.append((start, end))

        # Get top N synonyms
        synonyms = glossary[term][:max_synonyms]

        # Boost original term + add synonyms
        expansions.append(term)
        expansions.extend(synonyms)

        synonym_display = ", ".join(synonyms)
        applied.append(f"{term} -> {synonym_display}")

    if not expansions:
        return query, []

    expanded = query + " " + " ".join(expansions)
    return expanded, applied


def add_term(
    term: str,
    synonyms: list[str],
    glossary_path: Path | None = None,
) -> None:
    """Add a new term to the synonyms glossary file.

    Loads the existing glossary, adds the new entry, and writes
    back with yaml.safe_dump.

    Args:
        term: The term to add (will be lowercased).
        synonyms: List of synonym strings for this term.
        glossary_path: Path to synonyms.yml. Defaults to co-located file.
    """
    global _glossary_cache

    target_path = glossary_path or DEFAULT_GLOSSARY_PATH

    with open(target_path) as f:
        raw = yaml.safe_load(f) or {}

    raw[term.lower()] = synonyms

    with open(target_path, "w") as f:
        yaml.safe_dump(raw, f, default_flow_style=False, allow_unicode=True)

    # Invalidate cache
    _glossary_cache = None
