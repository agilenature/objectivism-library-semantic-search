"""Tests for query expansion engine with Objectivist terminology glossary.

Verifies synonym lookup, multi-word phrase matching, term boosting,
max synonyms limit, case-insensitive matching, and glossary loading.
"""

from __future__ import annotations

import pytest

from objlib.search.expansion import expand_query, load_glossary


class TestExpandKnownTerm:
    """Tests for expanding known glossary terms."""

    def test_expand_known_term(self):
        """expand_query('egoism') includes 'rational self-interest' synonym."""
        expanded, applied = expand_query("egoism")
        assert "rational self-interest" in expanded
        assert len(applied) > 0

    def test_expand_returns_original_plus_expansions(self):
        """Expanded query starts with the original query string."""
        expanded, applied = expand_query("What is egoism?")
        assert expanded.startswith("What is egoism?")
        assert len(applied) > 0


class TestExpandUnknownTerm:
    """Tests for queries with no glossary matches."""

    def test_expand_unknown_term_returns_original(self):
        """expand_query('quantum physics') returns original query unchanged."""
        expanded, applied = expand_query("quantum physics")
        assert expanded == "quantum physics"
        assert applied == []

    def test_expand_random_words_no_match(self):
        """Non-philosophical terms produce no expansions."""
        expanded, applied = expand_query("basketball weather forecast")
        assert expanded == "basketball weather forecast"
        assert applied == []


class TestMultiWordPhrases:
    """Tests for multi-word phrase matching."""

    def test_multi_word_phrase_matched(self):
        """'concept formation' matches as a phrase, not individual words."""
        expanded, applied = expand_query("concept formation")
        # Should match "concept formation" as a phrase
        assert any("concept formation" in a for a in applied)
        # Should include its synonym "abstraction"
        assert "abstraction" in expanded

    def test_rational_self_interest_matched_as_phrase(self):
        """'rational self-interest' matches as a single multi-word phrase."""
        expanded, applied = expand_query("rational self-interest")
        assert any("rational self-interest" in a for a in applied)


class TestTermBoosting:
    """Tests for original term boosting (appears twice in expanded query)."""

    def test_original_term_boosted(self):
        """Original matched term appears twice in expanded query (boosting)."""
        expanded, applied = expand_query("egoism")
        # The original query has "egoism" once, plus the boost adds it again
        # Expanded format: "egoism egoism rational self-interest selfishness"
        parts = expanded.split()
        egoism_count = parts.count("egoism")
        assert egoism_count >= 2, f"Expected 'egoism' at least twice, found {egoism_count} in: {expanded}"


class TestMaxSynonyms:
    """Tests for max_synonyms parameter."""

    def test_max_synonyms_limit_one(self):
        """With max_synonyms=1, only 1 synonym added per matched term."""
        expanded, applied = expand_query("egoism", max_synonyms=1)
        # Should have original + boost + 1 synonym
        # applied entry format: "egoism -> rational self-interest"
        assert len(applied) == 1
        # Only 1 synonym (not 2) after the arrow
        arrow_part = applied[0].split(" -> ")[1]
        # With max_synonyms=1, there should be exactly 1 synonym
        assert "," not in arrow_part, f"Expected 1 synonym, got: {arrow_part}"

    def test_max_synonyms_default_two(self):
        """Default max_synonyms=2 returns up to 2 synonyms per term."""
        expanded, applied = expand_query("egoism")
        # "egoism" has synonyms ["rational self-interest", "selfishness"]
        assert "rational self-interest" in expanded
        assert "selfishness" in expanded


class TestCaseInsensitive:
    """Tests for case-insensitive matching."""

    def test_case_insensitive_matching_uppercase(self):
        """expand_query('EGOISM') matches the lowercase glossary entry."""
        expanded, applied = expand_query("EGOISM")
        assert "rational self-interest" in expanded
        assert len(applied) > 0

    def test_case_insensitive_matching_mixed_case(self):
        """expand_query('Egoism') matches the lowercase glossary entry."""
        expanded, applied = expand_query("Egoism")
        assert "rational self-interest" in expanded


class TestMultipleTerms:
    """Tests for queries containing multiple glossary terms."""

    def test_multiple_terms_expanded(self):
        """Query with two glossary terms expands both."""
        expanded, applied = expand_query("egoism and altruism")
        assert len(applied) == 2
        terms_matched = [a.split(" -> ")[0] for a in applied]
        assert "egoism" in terms_matched
        assert "altruism" in terms_matched


class TestLoadGlossary:
    """Tests for glossary loading."""

    def test_load_glossary_returns_dict(self):
        """load_glossary() returns a dict with >40 entries."""
        glossary = load_glossary()
        assert isinstance(glossary, dict)
        assert len(glossary) > 40

    def test_glossary_entries_are_lists(self):
        """Every glossary value is a list of strings."""
        glossary = load_glossary()
        for term, synonyms in glossary.items():
            assert isinstance(synonyms, list), f"Synonyms for '{term}' is not a list"
            for s in synonyms:
                assert isinstance(s, str), f"Synonym '{s}' for '{term}' is not a string"


class TestLongestPhraseFirst:
    """Tests for longest-phrase-first matching to avoid partial overlaps."""

    def test_longest_phrase_first(self):
        """'rational self-interest' matches before 'interest' alone."""
        # "rational self-interest" is in glossary; if "interest" were also,
        # the longer phrase should win. We can verify by checking that
        # "rational self-interest" is matched as a phrase.
        expanded, applied = expand_query("rational self-interest is important")
        matched_terms = [a.split(" -> ")[0] for a in applied]
        assert "rational self-interest" in matched_terms

    def test_overlap_prevention(self):
        """Overlapping matches are prevented (longer phrase takes priority)."""
        # "concept formation" is a phrase in glossary. If both "concept" and
        # "concept formation" existed, only the longer should match.
        expanded, applied = expand_query("concept formation is key")
        matched_terms = [a.split(" -> ")[0] for a in applied]
        assert "concept formation" in matched_terms
        # Should not also match a shorter overlapping term
        assert len([t for t in matched_terms if "concept" in t]) == 1
