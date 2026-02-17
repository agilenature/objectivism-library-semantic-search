"""EntityExtractor: deterministic-first entity extraction with LLM fallback.

Pipeline stages:
A. Text normalization (casefold, strip punctuation, Unicode normalize)
B. Find candidate name spans via regex (capitalized word sequences, titles, possessives)
C. For each candidate:
   1. Check blocked alias list -> skip if blocked AND no full name nearby
   2. Exact match against canonical names/aliases (case-insensitive) -> confidence 1.0
   3. Strip possessive 's and re-check -> confidence 1.0
   4. Fuzzy match via RapidFuzz token_set_ratio:
      - >= 92: accept, confidence = score/100
      - 80-91: flag for LLM fallback
      - < 80: reject
D. Deduplicate: group by person_id, count mentions, track first_seen_char
E. LLM fallback for flagged candidates (optional)
F. Validate with Pydantic, reject confidence < 0.5
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from objlib.entities.models import EntityExtractionResult, TranscriptEntityOutput

if TYPE_CHECKING:
    from objlib.entities.registry import PersonRegistry

logger = logging.getLogger(__name__)

# Minimum confidence threshold for including entities in output
MIN_CONFIDENCE = 0.5

# Fuzzy match thresholds
FUZZY_ACCEPT = 92
FUZZY_MAYBE = 80

# Regex for candidate name spans: capitalized words with optional title prefix,
# possessive suffix, and multi-word names (1-3 tokens)
_TITLE_PREFIX = r"(?:(?:Dr|Prof|Professor|Mr|Mrs|Ms)\.?\s+)?"
_NAME_TOKEN = r"[A-Z][a-z]+"
_POSSESSIVE = r"(?:'s|'s)?"
_DE_PARTICLE = r"(?:\s+de\s+)?"

# Pattern for capitalized name sequences (1-3 words), with optional title and possessive
CANDIDATE_PATTERN = re.compile(
    _TITLE_PREFIX
    + _NAME_TOKEN + _POSSESSIVE
    + r"(?:" + _DE_PARTICLE + r"\s+" + _NAME_TOKEN + _POSSESSIVE + r"){0,2}"
)

# Speaker label pattern: "Name Name:" at line start
SPEAKER_LABEL_PATTERN = re.compile(
    r"^(" + _NAME_TOKEN + r"(?:\s+(?:de\s+)?" + _NAME_TOKEN + r")+):",
    re.MULTILINE,
)


class EntityExtractor:
    """Deterministic-first entity extraction with optional LLM fallback.

    Usage:
        extractor = EntityExtractor(registry)
        result = extractor.extract(text, "path/to/file.txt")
        for entity in result.entities:
            print(entity.person_id, entity.mention_count)
    """

    def __init__(self, registry: PersonRegistry, mistral_client: object | None = None) -> None:
        self.registry = registry
        self.mistral_client = mistral_client

        # Build lookup structures for fast matching
        self._canonical_names: dict[str, str] = {}  # casefold name -> person_id
        self._alias_map: dict[str, str] = {}  # casefold alias -> person_id (non-blocked only)
        self._blocked_set: set[str] = set()
        self._all_matchable: list[tuple[str, str]] = []  # (casefold text, person_id) for fuzzy

        self._build_lookups()

    def _build_lookups(self) -> None:
        """Build fast lookup structures from registry."""
        for person in self.registry.all_persons():
            self._canonical_names[person.canonical_name.casefold()] = person.person_id

        for alias in self.registry.all_aliases():
            key = alias.alias_text.casefold()
            if alias.is_blocked:
                self._blocked_set.add(key)
            else:
                self._alias_map[key] = alias.person_id

        # Build fuzzy match candidates from all non-blocked aliases + canonical names
        for name_lower, pid in self._canonical_names.items():
            self._all_matchable.append((name_lower, pid))
        for alias_lower, pid in self._alias_map.items():
            self._all_matchable.append((alias_lower, pid))

    def extract(self, text: str, file_path: str) -> EntityExtractionResult:
        """Extract entities from transcript text.

        Args:
            text: The transcript text to extract entities from.
            file_path: Path of the source file (for result metadata).

        Returns:
            EntityExtractionResult with validated entities.
        """
        if not text or not text.strip():
            return EntityExtractionResult(
                file_path=file_path,
                entities=[],
                status="entities_done",
            )

        # Find all candidate spans
        candidates = self._find_candidates(text)

        # Match each candidate against registry
        # matches: list of (person_id, confidence, start_char, surface_text)
        matches: list[tuple[str, float, int, str]] = []
        flagged_for_llm: list[tuple[str, int, str]] = []  # (surface_text, start_char, context)

        for surface_text, start_char, end_char in candidates:
            person_id, confidence = self._match_candidate(surface_text, text, start_char)
            if person_id is not None and confidence >= MIN_CONFIDENCE:
                matches.append((person_id, confidence, start_char, surface_text))
            elif confidence > 0 and confidence < MIN_CONFIDENCE:
                # Below threshold but non-zero: potential LLM candidate
                pass

        # LLM fallback for flagged candidates (if client available)
        # For now, discard flagged candidates without LLM client
        if self.mistral_client and flagged_for_llm:
            # TODO: Implement LLM fallback for 80-91 range
            pass

        # Deduplicate: group by person_id
        entities = self._deduplicate(matches, text)

        # Filter by confidence threshold
        entities = [e for e in entities if e.max_confidence >= MIN_CONFIDENCE]

        return EntityExtractionResult(
            file_path=file_path,
            entities=entities,
            status="entities_done",
        )

    def _find_candidates(self, text: str) -> list[tuple[str, int, int]]:
        """Find candidate name spans in text.

        Returns list of (surface_text, start_char, end_char).
        Finds capitalized word sequences, title+name patterns,
        possessive forms, and speaker labels.
        """
        candidates: list[tuple[str, int, int]] = []
        seen_spans: set[tuple[int, int]] = set()

        # Find speaker labels first (higher priority)
        for match in SPEAKER_LABEL_PATTERN.finditer(text):
            span = (match.start(1), match.end(1))
            if span not in seen_spans:
                seen_spans.add(span)
                candidates.append((match.group(1), span[0], span[1]))

        # Find general candidate name patterns
        for match in CANDIDATE_PATTERN.finditer(text):
            span = (match.start(), match.end())
            # Skip if overlapping with already found span
            if any(s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1] for s in seen_spans):
                continue
            seen_spans.add(span)
            candidates.append((match.group(), span[0], span[1]))

        return candidates

    def _match_candidate(
        self, surface_text: str, full_text: str, start_char: int
    ) -> tuple[str | None, float]:
        """Match a candidate surface text against registry.

        Returns (person_id, confidence) or (None, 0.0).
        Handles blocked aliases, exact matches, possessives, and fuzzy.
        """
        normalized = surface_text.strip()
        lower = normalized.casefold()

        # Strip possessive for matching
        stripped = lower
        if stripped.endswith("'s") or stripped.endswith("\u2019s"):
            stripped = stripped[:-2].rstrip()

        # Check if blocked
        # For multi-word tokens, check each word and the full token
        tokens = stripped.split()
        is_single_word = len(tokens) == 1

        if is_single_word and stripped in self._blocked_set:
            # Blocked single word -- check if full name appears nearby
            if not self._full_name_nearby(stripped, full_text, start_char):
                return (None, 0.0)

        # 1. Exact match against canonical names (casefolded)
        if stripped in self._canonical_names:
            return (self._canonical_names[stripped], 1.0)

        # 2. Exact match against aliases (casefolded, non-blocked)
        if stripped in self._alias_map:
            return (self._alias_map[stripped], 1.0)

        # 3. Try the original (with possessive) form against aliases
        if lower != stripped:
            if lower in self._canonical_names:
                return (self._canonical_names[lower], 1.0)
            if lower in self._alias_map:
                return (self._alias_map[lower], 1.0)

        # 4. Try with title prefix stripped for alias match
        title_stripped = self._strip_title(stripped)
        if title_stripped != stripped:
            if title_stripped in self._canonical_names:
                return (self._canonical_names[title_stripped], 1.0)
            if title_stripped in self._alias_map:
                return (self._alias_map[title_stripped], 1.0)

        # 5. Fuzzy match
        return self._fuzzy_match(stripped)

    def _strip_title(self, text: str) -> str:
        """Strip common title prefixes from text."""
        prefixes = ["dr. ", "dr ", "prof. ", "prof ", "professor ", "mr. ", "mr ",
                     "mrs. ", "mrs ", "ms. ", "ms "]
        lower = text.casefold()
        for prefix in prefixes:
            if lower.startswith(prefix):
                return lower[len(prefix):]
        return text

    def _full_name_nearby(self, blocked_token: str, full_text: str, position: int, window: int = 200) -> bool:
        """Check if a full (disambiguated) name appears near a blocked alias.

        Looks within +-window chars for a full name alias that resolves
        the ambiguity of the blocked token.
        """
        start = max(0, position - window)
        end = min(len(full_text), position + window)
        context = full_text[start:end].casefold()

        # Check all non-blocked aliases that contain the blocked token
        for alias_lower, person_id in self._alias_map.items():
            if blocked_token in alias_lower.split() and len(alias_lower.split()) > 1:
                # This is a multi-word alias containing the blocked token
                if alias_lower in context:
                    return True

        # Also check canonical names
        for name_lower, person_id in self._canonical_names.items():
            if blocked_token in name_lower.split() and len(name_lower.split()) > 1:
                if name_lower in context:
                    return True

        return False

    def _fuzzy_match(self, text: str) -> tuple[str | None, float]:
        """Fuzzy match against all canonical names and aliases.

        Uses rapidfuzz.fuzz.token_set_ratio.
        Returns (person_id, confidence) or (None, 0.0).
        """
        if not text or len(text) < 3:
            return (None, 0.0)

        best_score = 0.0
        best_person_id: str | None = None

        for candidate_text, person_id in self._all_matchable:
            score = fuzz.token_set_ratio(text, candidate_text)
            if score > best_score:
                best_score = score
                best_person_id = person_id

        if best_score >= FUZZY_ACCEPT:
            return (best_person_id, best_score / 100.0)
        elif best_score >= FUZZY_MAYBE:
            # Flag for LLM fallback (if available) -- for now, discard
            return (None, 0.0)
        else:
            return (None, 0.0)

    def _deduplicate(
        self, matches: list[tuple[str, float, int, str]], text: str
    ) -> list[TranscriptEntityOutput]:
        """Group matches by person_id and produce entity output.

        For each person: count total mentions, record first_seen_char,
        compute max_confidence, capture evidence_sample.
        """
        groups: dict[str, dict] = {}

        for person_id, confidence, start_char, surface_text in matches:
            if person_id not in groups:
                groups[person_id] = {
                    "mention_count": 0,
                    "first_seen_char": start_char,
                    "max_confidence": 0.0,
                    "evidence_start": start_char,
                }
            groups[person_id]["mention_count"] += 1
            groups[person_id]["max_confidence"] = max(
                groups[person_id]["max_confidence"], confidence
            )
            if start_char < groups[person_id]["first_seen_char"]:
                groups[person_id]["first_seen_char"] = start_char
                groups[person_id]["evidence_start"] = start_char

        entities: list[TranscriptEntityOutput] = []
        for person_id, data in groups.items():
            canonical_name = self.registry.get_canonical_name(person_id) or person_id

            # Extract evidence sample: +-50 chars around first mention
            ev_start = max(0, data["evidence_start"] - 50)
            ev_end = min(len(text), data["evidence_start"] + 50)
            evidence = text[ev_start:ev_end].strip()
            if len(evidence) > 200:
                evidence = evidence[:200]

            entities.append(
                TranscriptEntityOutput(
                    person_id=person_id,
                    canonical_name=canonical_name,
                    mention_count=data["mention_count"],
                    max_confidence=data["max_confidence"],
                    evidence_sample=evidence,
                    first_seen_char=data["first_seen_char"],
                )
            )

        return entities
