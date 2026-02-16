"""Two-phase response parser for Mistral magistral model outputs.

Magistral models return content as a list of typed chunks:
- ThinkChunk (type='thinking'): reasoning traces
- TextChunk (type='text'): the actual JSON output

Non-reasoning models return content as a plain string.

This parser handles both formats with a regex fallback for
malformed responses.
"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_magistral_response(response: Any) -> dict:
    """Extract and parse JSON from a Mistral chat completion response.

    Implements a multi-phase parsing strategy:
      Phase 1: If content is a list of chunk objects, extract text segments
               (filter where type == 'text'), concatenate, and json.loads().
      Phase 2: If content is a string, try json.loads() directly.
      Phase 3: Regex fallback -- find last complete JSON object in the
               string representation (handles at least one level of nesting
               for the semantic_description field).
      Phase 4: Raise ValueError if no valid JSON found.

    Args:
        response: Mistral ChatCompletionResponse (or compatible mock with
                  response.choices[0].message.content).

    Returns:
        Parsed dict from the JSON payload.

    Raises:
        ValueError: If no valid JSON can be extracted from the response.
    """
    content = response.choices[0].message.content

    # Phase 1: List of chunk objects (magistral models)
    if isinstance(content, list):
        text_parts: list[str] = []
        for chunk in content:
            # SDK TextChunk has type='text' and .text attribute
            # SDK ThinkChunk has type='thinking' -- skip it
            chunk_type = getattr(chunk, "type", None)
            if chunk_type == "text":
                text_parts.append(getattr(chunk, "text", ""))
        if text_parts:
            combined = "".join(text_parts)
            try:
                return json.loads(combined)
            except json.JSONDecodeError:
                pass
            # Fall through to regex on combined text
            result = _regex_extract_json(combined)
            if result is not None:
                return result

    # Phase 2: Plain string content
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # Fall through to regex
        result = _regex_extract_json(content)
        if result is not None:
            return result

    # Phase 3: Last resort -- stringify the whole content and regex
    content_str = str(content)
    result = _regex_extract_json(content_str)
    if result is not None:
        return result

    # Phase 4: Nothing worked
    raise ValueError("No valid JSON found in response")


def _regex_extract_json(text: str) -> dict | None:
    """Find the last complete JSON object in text using regex.

    Handles at least one level of brace nesting (required for
    semantic_description which contains nested objects).

    Args:
        text: String that may contain a JSON object.

    Returns:
        Parsed dict if a valid JSON object is found, None otherwise.
    """
    # Match a JSON object with up to two levels of nesting
    # Pattern: { ... { ... } ... } allowing nested braces
    pattern = r"\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}"
    matches = re.findall(pattern, text, re.DOTALL)

    # Try from last match (most likely to be the final answer)
    for match in reversed(matches):
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    return None
