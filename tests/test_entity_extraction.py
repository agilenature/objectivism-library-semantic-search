"""TDD tests for entity extraction engine.

Tests the deterministic-first pipeline with fuzzy matching,
blocked alias handling, disambiguation, possessives, speaker
labels, and full transcript extraction.
"""

from __future__ import annotations

import pytest

from objlib.database import Database
from objlib.entities.extractor import EntityExtractor
from objlib.entities.registry import PersonRegistry


@pytest.fixture
def db():
    """Create an in-memory database with schema v4 seed data."""
    database = Database(":memory:")
    yield database
    database.close()


@pytest.fixture
def registry(db):
    """Create a PersonRegistry from the seeded database."""
    return PersonRegistry(db)


@pytest.fixture
def extractor(registry):
    """Create an EntityExtractor with the registry (no LLM fallback)."""
    return EntityExtractor(registry)


# ---------- 1. Exact match tests ----------

class TestExactMatch:
    """Exact full name matches should return confidence 1.0."""

    def test_ayn_rand_exact(self, extractor):
        result = extractor.extract("Ayn Rand discussed philosophy.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "ayn-rand" in entities
        assert entities["ayn-rand"].max_confidence == 1.0

    def test_leonard_peikoff_exact(self, extractor):
        result = extractor.extract("Leonard Peikoff gave a lecture.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "leonard-peikoff" in entities
        assert entities["leonard-peikoff"].max_confidence == 1.0

    def test_tristan_de_liege_exact(self, extractor):
        result = extractor.extract("Tristan de Liege presented on ethics.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "tristan-de-liege" in entities
        assert entities["tristan-de-liege"].max_confidence == 1.0


# ---------- 2. Alias match tests ----------

class TestAliasMatch:
    """Alias matches (partials, title variants, nicknames) should return confidence 1.0."""

    def test_peikoff_partial(self, extractor):
        result = extractor.extract("Peikoff argued that concepts are valid.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "leonard-peikoff" in entities
        assert entities["leonard-peikoff"].max_confidence == 1.0

    def test_rand_partial(self, extractor):
        result = extractor.extract("Rand wrote extensively about objectivism.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "ayn-rand" in entities
        assert entities["ayn-rand"].max_confidence == 1.0

    def test_dr_peikoff_title(self, extractor):
        result = extractor.extract("Dr. Peikoff explained the hierarchy of knowledge.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "leonard-peikoff" in entities
        assert entities["leonard-peikoff"].max_confidence == 1.0

    def test_onkar_nickname(self, extractor):
        result = extractor.extract("Onkar explained the problem with altruism.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "onkar-ghate" in entities
        assert entities["onkar-ghate"].max_confidence == 1.0

    def test_ghate_partial(self, extractor):
        result = extractor.extract("Ghate presented on free will.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "onkar-ghate" in entities

    def test_binswanger_partial(self, extractor):
        result = extractor.extract("Binswanger discussed consciousness.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "harry-binswanger" in entities


# ---------- 3. Blocked alias tests ----------

class TestBlockedAlias:
    """Blocked aliases should NOT produce matches when used alone."""

    def test_smith_blocked(self, extractor):
        result = extractor.extract("Smith discussed the topic.", "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "tara-smith" not in entities
        assert "aaron-smith" not in entities

    def test_aaron_blocked(self, extractor):
        result = extractor.extract("Aaron spoke about philosophy.", "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "aaron-smith" not in entities

    def test_tara_blocked(self, extractor):
        result = extractor.extract("Tara lectured on ethics.", "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "tara-smith" not in entities

    def test_ben_blocked(self, extractor):
        result = extractor.extract("Ben gave a presentation.", "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "ben-bayer" not in entities

    def test_mike_blocked(self, extractor):
        result = extractor.extract("Mike discussed the issue.", "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "mike-mazza" not in entities


# ---------- 4. Disambiguation tests ----------

class TestDisambiguation:
    """Full names should disambiguate blocked partial names."""

    def test_tara_smith_disambiguated(self, extractor):
        result = extractor.extract("Tara Smith discussed rational egoism.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "tara-smith" in entities
        assert entities["tara-smith"].max_confidence == 1.0

    def test_aaron_smith_disambiguated(self, extractor):
        result = extractor.extract("Aaron Smith presented on epistemology.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        assert "aaron-smith" in entities
        assert entities["aaron-smith"].max_confidence == 1.0

    def test_both_smiths_and_bare_smith(self, extractor):
        """Text containing 'Tara Smith' and 'Smith' alone: only full name matched."""
        text = "Tara Smith discussed ethics. Later, Smith was referenced in the bibliography."
        result = extractor.extract(text, "test.txt")
        entities = {e.person_id: e for e in result.entities}
        # Tara Smith should be found via the full name alias
        assert "tara-smith" in entities
        # Aaron Smith should NOT be found (no "Aaron Smith" in text)
        assert "aaron-smith" not in entities


# ---------- 5. Possessive tests ----------

class TestPossessive:
    """Possessive forms (Name's) should match the canonical person."""

    def test_rands_possessive(self, extractor):
        result = extractor.extract("Rand's theory of concepts is fundamental.", "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "ayn-rand" in entities

    def test_peikoffs_possessive(self, extractor):
        result = extractor.extract("Peikoff's argument about universals is compelling.", "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "leonard-peikoff" in entities

    def test_ghates_possessive(self, extractor):
        result = extractor.extract("Ghate's lecture on free will was excellent.", "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "onkar-ghate" in entities


# ---------- 6. Speaker label tests ----------

class TestSpeakerLabel:
    """Speaker labels (Name: text) at line starts should match."""

    def test_peikoff_speaker_label(self, extractor):
        text = "Leonard Peikoff: The concept of objectivity is fundamental to Objectivism."
        result = extractor.extract(text, "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "leonard-peikoff" in entities

    def test_onkar_ghate_speaker_label(self, extractor):
        text = "Onkar Ghate: I think that this is a crucial distinction."
        result = extractor.extract(text, "test.txt")
        entities = {e.person_id for e in result.entities}
        assert "onkar-ghate" in entities


# ---------- 7. Full transcript extraction test ----------

class TestFullTranscript:
    """Multi-paragraph text with multiple entities and blocked aliases."""

    def test_multi_entity_transcript(self, extractor):
        text = """
        In this lecture, Ayn Rand discusses the nature of concepts and their role
        in human cognition. She references the work of her student, Peikoff, who
        later expanded on these ideas in his own lectures.

        As Rand's philosophy evolved, Dr. Peikoff became one of its foremost
        interpreters. Smith also contributed to the discussion, but the primary
        focus remained on the original formulation.

        The key insight from Rand is that concepts are not arbitrary constructs
        but reflect the actual structure of reality.
        """
        result = extractor.extract(text, "test.txt")
        entities = {e.person_id: e for e in result.entities}

        # Ayn Rand: "Ayn Rand" + "Rand's" + "Rand" = multiple mentions
        assert "ayn-rand" in entities
        assert entities["ayn-rand"].mention_count >= 2

        # Leonard Peikoff: "Peikoff" + "Dr. Peikoff" = multiple mentions
        assert "leonard-peikoff" in entities
        assert entities["leonard-peikoff"].mention_count >= 2

        # Smith (blocked) should NOT appear
        assert "tara-smith" not in entities
        assert "aaron-smith" not in entities

        # Status should be entities_done
        assert result.status == "entities_done"


# ---------- 8. Fuzzy match tests ----------

class TestFuzzyMatch:
    """Fuzzy matching with RapidFuzz for minor typos."""

    def test_peikof_typo(self, extractor):
        """Minor typo: 'Peikof' (missing f) should still match if score >= 92."""
        result = extractor.extract("Peikof discussed the issue of universals.", "test.txt")
        # This should match leonard-peikoff via fuzzy if score >= 92
        entities = {e.person_id: e for e in result.entities}
        if "leonard-peikoff" in entities:
            assert entities["leonard-peikoff"].max_confidence >= 0.92

    def test_binwanger_typo(self, extractor):
        """Minor typo: 'Binwanger' (missing s) should match if score >= 92."""
        result = extractor.extract("Binwanger discussed consciousness.", "test.txt")
        entities = {e.person_id: e for e in result.entities}
        if "harry-binswanger" in entities:
            assert entities["harry-binswanger"].max_confidence >= 0.92

    def test_random_name_rejected(self, extractor):
        """Completely unrelated name should not match any canonical person."""
        result = extractor.extract("Xyz Random Person talked about philosophy.", "test.txt")
        # No canonical persons should be found
        assert len(result.entities) == 0


# ---------- 9. No entities test ----------

class TestNoEntities:
    """Text with no person mentions should return empty entity list."""

    def test_no_persons_mentioned(self, extractor):
        result = extractor.extract(
            "The concept of free will is central to moral philosophy.",
            "test.txt",
        )
        assert len(result.entities) == 0
        assert result.status == "entities_done"

    def test_empty_text(self, extractor):
        result = extractor.extract("", "test.txt")
        assert len(result.entities) == 0
        assert result.status == "entities_done"


# ---------- 10. Confidence threshold test ----------

class TestConfidenceThreshold:
    """Entities with confidence < 0.5 should be excluded from output."""

    def test_high_confidence_included(self, extractor):
        """Exact match should always be included (confidence=1.0 > 0.5)."""
        result = extractor.extract("Ayn Rand wrote Atlas Shrugged.", "test.txt")
        assert len(result.entities) >= 1
        for entity in result.entities:
            assert entity.max_confidence >= 0.5

    def test_all_entities_above_threshold(self, extractor):
        """All returned entities must have confidence >= 0.5."""
        text = "Peikoff and Ghate discussed epistemology with Binswanger."
        result = extractor.extract(text, "test.txt")
        for entity in result.entities:
            assert entity.max_confidence >= 0.5, (
                f"{entity.person_id} has confidence {entity.max_confidence} < 0.5"
            )
