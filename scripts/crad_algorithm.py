"""CRAD Algorithm: Corpus-Relative Aspect Differentiation via the Genus Method.

3-pass algorithm for generating discrimination phrases:
  Pass 1 (Genus Identification): Pure DB computation — aspect frequency within series
  Pass 2 (Differential Identification): Claude selects philosophically specific differentia
  Pass 3 (Essentialization): Concatenate top aspects into <=7-word phrase

Phase 16.6 — Objectivism Library Semantic Search
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

# -- Constants ----------------------------------------------------------------

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
GENUS_THRESHOLD_PCT = 0.80  # aspects in >=80% of series files are genus
MAX_PHRASE_WORDS = 7


# -- DB Schema ----------------------------------------------------------------

CRAD_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS series_genus (
    series_name TEXT PRIMARY KEY,
    genus_profile_json TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    last_updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_discrimination_phrases (
    filename TEXT PRIMARY KEY,
    series_name TEXT NOT NULL,
    phrase TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    aspects_used TEXT NOT NULL,
    validation_rank INTEGER,
    validation_status TEXT NOT NULL DEFAULT 'candidate',
    last_validated TEXT
);
"""


def create_crad_tables(conn: sqlite3.Connection) -> None:
    """Create CRAD tables if they don't exist."""
    conn.executescript(CRAD_SCHEMA_SQL)
    conn.commit()


# -- Corpus Frequency Map ----------------------------------------------------

def build_corpus_freq_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Build aspect frequency map across ALL files in the corpus.

    Used as secondary context for Pass 2 (Claude prompt includes corpus freq
    alongside series freq for each target aspect).
    """
    freq: dict[str, int] = {}
    rows = conn.execute(
        "SELECT metadata_json FROM file_metadata_ai WHERE is_current = 1"
    ).fetchall()
    for (mj,) in rows:
        if not mj:
            continue
        try:
            for a in json.loads(mj).get("topic_aspects", []):
                freq[a] = freq.get(a, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass
    return freq


# -- Pass 1: Genus Identification --------------------------------------------

def build_genus_profile(conn: sqlite3.Connection, parent_dir_name: str) -> dict:
    """Build genus profile for all files in a series (identified by parent dir).

    Queries file_metadata_ai (via JOIN with files table, since file_metadata_ai
    has file_path not filename) for all indexed files in the given parent directory.

    Returns dict with:
        series_name: str
        file_count: int
        shared_aspects: list[str]  -- aspects in >=80% of series files (genus)
        aspect_frequency_map: dict[str, int]  -- {aspect: count_of_files}
        rarity_threshold: int  -- currently 2
        files_aspects: dict[str, list[str]]  -- {filename: [aspect, ...]} for all files
    """
    rows = conn.execute("""
        SELECT f.filename, fma.metadata_json
        FROM files f
        JOIN file_metadata_ai fma ON fma.file_path = f.file_path AND fma.is_current = 1
        WHERE f.gemini_state = 'indexed'
          AND f.file_path LIKE ?
    """, (f"%/{parent_dir_name}/%",)).fetchall()

    freq: dict[str, int] = {}
    files_aspects: dict[str, list[str]] = {}
    file_count = len(rows)

    for filename, mj in rows:
        if not mj:
            files_aspects[filename] = []
            continue
        try:
            aspects = json.loads(mj).get("topic_aspects", [])
        except (json.JSONDecodeError, TypeError):
            aspects = []
        files_aspects[filename] = aspects
        for a in aspects:
            freq[a] = freq.get(a, 0) + 1

    threshold_80pct = max(1, int(file_count * GENUS_THRESHOLD_PCT))
    shared = [a for a, c in freq.items() if c >= threshold_80pct]

    return {
        "series_name": parent_dir_name,
        "file_count": file_count,
        "shared_aspects": shared,
        "aspect_frequency_map": freq,
        "rarity_threshold": 2,
        "files_aspects": files_aspects,
    }


# -- Pass 2: Claude-driven Differential Identification -----------------------

def _build_pass2_system_prompt() -> str:
    return """You are a philosophical librarian applying the Genus Method to build a
discrimination index for an Objectivism lecture library.

Your task: given a target lecture file and all sibling files in the same series,
identify the 1-3 aspects that make the TARGET file philosophically distinct from ALL
its siblings. Output ONLY valid JSON — no prose before or after.

Rules:
1. Prefer aspects that are philosophically SPECIFIC over philosophically generic.
   "Zeno's arrow paradox" is specific. "epistemology" is generic.
   "measurement omission in concept formation" is specific. "methodology" is generic.
2. Prefer aspects that appear in FEW or NO sibling files (use the frequency hint).
   But when many aspects tie at the same frequency, judge by philosophical specificity.
3. Select 1-3 aspects whose concatenation totals <=7 words.
4. Do NOT include aspects that appear in >=80% of sibling files — those are genus, not differentia.
5. Do NOT use markdown, bullet points, or explanation outside the JSON object.

Output format (ONLY this JSON, nothing else):
{
  "discrimination_phrase": "the concatenated phrase, <=7 words, no markdown",
  "aspects_used": ["aspect1", "aspect2"],
  "reasoning": "one sentence explaining why these aspects are the most specific differentia"
}"""


def _build_pass2_user_message(
    target_filename: str,
    target_aspects: list[str],
    series_name: str,
    series_aspects_by_file: dict[str, list[str]],
    series_freq_map: dict[str, int],
    corpus_freq_map: dict[str, int],
) -> str:
    """Build the user message for Pass 2 Claude call."""
    # Build sibling table: only the siblings (exclude target)
    sibling_lines = []
    for fname, aspects in sorted(series_aspects_by_file.items()):
        if fname == target_filename:
            continue
        sibling_lines.append(f"  {fname}: {', '.join(aspects[:8])}")  # cap at 8 per sibling

    # Frequency hint: target's aspects with their series and corpus frequencies
    freq_lines = []
    for aspect in target_aspects:
        s_freq = series_freq_map.get(aspect, 0)
        c_freq = corpus_freq_map.get(aspect, 0)
        freq_lines.append(f"  [{s_freq} in series, {c_freq} in corpus] {aspect}")

    return f"""Series: {series_name}
Series size: {len(series_aspects_by_file)} files

TARGET FILE: {target_filename}
Target aspects: {', '.join(target_aspects)}

SIBLING FILES (all other files in series):
{chr(10).join(sibling_lines)}

FREQUENCY HINT for target's aspects (series_count, corpus_count):
{chr(10).join(freq_lines)}

Select the 1-3 aspects that make {target_filename} philosophically DISTINCT from all siblings.
Output ONLY the JSON object."""


def get_claude_discrimination_phrase(
    target_filename: str,
    target_aspects: list[str],
    series_name: str,
    series_aspects_by_file: dict[str, list[str]],
    series_freq_map: dict[str, int],
    corpus_freq_map: dict[str, int],
    max_retries: int = 2,
) -> dict:
    """Call Claude to select the philosophically discriminating aspects for target_filename.

    Returns dict with keys:
        discrimination_phrase: str   -- the 1-7 word discrimination phrase
        aspects_used: list[str]      -- the 1-3 aspects Claude selected
        reasoning: str               -- Claude's explanation (for audit log)
        model: str                   -- model used
    Raises ValueError if Claude fails to return valid JSON after max_retries attempts.
    Raises RuntimeError for Anthropic API errors (including auth).
    """
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    system_prompt = _build_pass2_system_prompt()
    user_message = _build_pass2_user_message(
        target_filename=target_filename,
        target_aspects=target_aspects,
        series_name=series_name,
        series_aspects_by_file=series_aspects_by_file,
        series_freq_map=series_freq_map,
        corpus_freq_map=corpus_freq_map,
    )

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=512,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            parsed = json.loads(text)
            if "discrimination_phrase" not in parsed or "aspects_used" not in parsed:
                raise ValueError(
                    f"Missing required keys in response: {list(parsed.keys())}"
                )
            return {
                "discrimination_phrase": parsed["discrimination_phrase"],
                "aspects_used": parsed["aspects_used"],
                "reasoning": parsed.get("reasoning", ""),
                "model": CLAUDE_MODEL,
            }
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(1)
            continue
        except anthropic.APIError as e:
            raise RuntimeError(f"Anthropic API error: {e}") from e

    raise ValueError(
        f"Claude failed to return valid JSON after {max_retries + 1} attempts. "
        f"Last error: {last_error}"
    )


# -- Pass 3: Essentialization ------------------------------------------------

def build_discrimination_phrase(differentia: dict, max_words: int = MAX_PHRASE_WORDS) -> dict:
    """Concatenate top aspects into <=max_words phrase. Strip markdown.

    Args:
        differentia: dict with keys 'filename', 'series_name', and either
                     'aspects_used' (from Claude) or 'top_3_rarest' (from freq sort)
        max_words: maximum word count for the phrase (default 7)

    Returns dict with:
        filename, series_name, phrase, word_count, aspects_used, validation_status
    """
    def clean(aspect: str) -> str:
        return re.sub(r'[*_`]', '', aspect).strip()

    # Accept aspects from either Claude output or frequency-sorted output
    aspects_to_use = differentia.get("aspects_used", differentia.get("top_3_rarest", []))

    words_used: list[str] = []
    aspects_used_final: list[str] = []
    for aspect in aspects_to_use:
        cleaned = clean(aspect)
        words = cleaned.split()
        if len(words_used) + len(words) <= max_words:
            words_used.extend(words)
            aspects_used_final.append(aspect)
        else:
            break  # word budget exhausted

    phrase = " ".join(words_used)
    return {
        "filename": differentia["filename"],
        "series_name": differentia["series_name"],
        "phrase": phrase,
        "word_count": len(words_used),
        "aspects_used": aspects_used_final,
        "validation_status": "candidate",
    }


# -- Validation against Gemini -----------------------------------------------

def validate_phrase(
    client,  # google.genai.Client
    store_resource_name: str,
    phrase: str,
    target_store_doc_id: str,
    search_model: str = "gemini-2.5-flash",
    top_k: int = 20,
) -> int | None:
    """Query Gemini File Search with the discrimination phrase.

    Return the rank (1-indexed) of the target file, or None if not found in top_k.

    Matching uses the store_doc_id prefix (first 12 chars before first '-'),
    which is the identity contract from Phase 16.1.

    Args:
        client: google.genai.Client instance
        store_resource_name: full store resource name
        phrase: the discrimination phrase to search
        target_store_doc_id: the gemini_store_doc_id from DB (e.g., "abcdef123456-xxxx")
        search_model: Gemini model to use (default "gemini-2.5-flash")
        top_k: max results to check (default 20)

    Returns:
        1-indexed rank if found, None otherwise
    """
    from google.genai import types as genai_types

    try:
        response = client.models.generate_content(
            model=search_model,
            contents=phrase,
            config=genai_types.GenerateContentConfig(
                tools=[genai_types.Tool(
                    file_search=genai_types.FileSearch(
                        file_search_store_names=[store_resource_name]
                    )
                )]
            ),
        )
    except Exception as e:
        print(f"    Gemini query error: {e}", file=sys.stderr)
        return None

    # Extract store_doc_id prefix (first 12 chars before first '-')
    if target_store_doc_id and '-' in target_store_doc_id:
        target_prefix = target_store_doc_id.split('-')[0]
    else:
        target_prefix = target_store_doc_id or ""

    # Check grounding chunks (same pattern as check_stability.py A7)
    if not response.candidates:
        return None

    gm = getattr(response.candidates[0], "grounding_metadata", None)
    if not gm:
        return None

    chunks = getattr(gm, "grounding_chunks", []) or []
    for i, chunk in enumerate(chunks[:top_k]):
        rc = getattr(chunk, "retrieved_context", None)
        if not rc:
            continue
        title = getattr(rc, "title", "") or ""
        if target_prefix and title == target_prefix:
            return i + 1

    return None


# -- DB Storage ---------------------------------------------------------------

def store_genus_profile(conn: sqlite3.Connection, genus: dict) -> None:
    """Store a genus profile in the series_genus table."""
    conn.execute("""
        INSERT OR REPLACE INTO series_genus (series_name, genus_profile_json, file_count, last_updated)
        VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    """, (
        genus["series_name"],
        json.dumps({
            "shared_aspects": genus["shared_aspects"],
            "aspect_frequency_map": genus["aspect_frequency_map"],
            "rarity_threshold": genus["rarity_threshold"],
        }),
        genus["file_count"],
    ))
    conn.commit()


def store_discrimination_phrase(conn: sqlite3.Connection, result: dict) -> None:
    """Store a discrimination phrase result in file_discrimination_phrases table."""
    conn.execute("""
        INSERT OR REPLACE INTO file_discrimination_phrases
        (filename, series_name, phrase, word_count, aspects_used,
         validation_rank, validation_status, last_validated)
        VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    """, (
        result["filename"],
        result["series_name"],
        result["phrase"],
        result["word_count"],
        json.dumps(result["aspects_used"]),
        result.get("validation_rank"),
        result.get("validation_status", "candidate"),
    ))
    conn.commit()
