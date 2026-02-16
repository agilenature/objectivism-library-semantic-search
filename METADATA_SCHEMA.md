# Metadata Schema for Objectivism Library

## Overview

This document defines the complete metadata schema for every file in the Objectivism Library. The schema preserves the intellectual and pedagogical structure while enabling powerful semantic search.

## Schema Principles

1. **Comprehensive**: Capture all meaningful organizational information
2. **Semantic**: Enable concept-based search
3. **Hierarchical**: Preserve pedagogical sequences
4. **Relational**: Track connections between content
5. **Extensible**: Easy to add new metadata fields

## Complete Metadata Structure

```json
{
  "core": {
    "file_id": "string (Gemini file ID)",
    "source_path": "string (relative path from library root)",
    "filename": "string (original filename)",
    "file_size_bytes": "integer",
    "upload_timestamp": "ISO 8601 datetime",
    "content_hash": "string (SHA256 for deduplication)"
  },

  "classification": {
    "primary_category": "enum (Book | Course | MOTM | Podcast | Conference | HBTV | Other)",
    "content_type": "enum (Lecture | BookChapter | Discussion | QA | OfficeHour | Interview)",
    "format": "enum (Transcript | Notes | Slides | Handout)",
    "language": "string (default: en)"
  },

  "intellectual": {
    "title": "string (human-readable title)",
    "subtitle": "string (optional)",
    "topics": ["array of strings (main topics covered)"],
    "subtopics": ["array of strings (detailed topics)"],
    "key_concepts": ["array of strings (specific philosophical concepts)"],
    "key_terms_defined": ["array of strings (terms explicitly defined)"],
    "philosophers_discussed": ["array of strings (thinkers referenced)"],
    "books_referenced": ["array of strings (works cited)"],
    "arguments_presented": ["array of strings (main arguments)"],
    "questions_addressed": ["array of strings (Q&A topics)"]
  },

  "instructional": {
    "instructor": "string (primary instructor/author)",
    "co_instructors": ["array of strings (if applicable)"],
    "difficulty_level": "enum (Foundations | Intermediate | Advanced | Expert)",
    "prerequisites": ["array of strings (what to know first)"],
    "builds_on": ["array of file_ids (direct prerequisites)"],
    "prepares_for": ["array of file_ids (what comes next)"],
    "estimated_study_time_minutes": "integer (optional)"
  },

  "pedagogical_structure": {
    "course_name": "string (if part of a course)",
    "course_sequence": {
      "year": "string (Year1, Year2, etc.)",
      "quarter": "string (Q1, Q2, Q3, Q4)",
      "week": "string (Week1, Week2, etc.)",
      "session": "integer (for non-week-based courses)",
      "class_number": "integer (alternative to week)",
      "part": "string (Part1, Part2 for multi-part series)"
    },
    "curriculum_stage": "enum (Introduction | Development | Integration | Application | Review)",
    "within_course_position": "integer (1 for first, N for Nth)",
    "total_course_length": "integer (total sessions in course)"
  },

  "temporal": {
    "recording_date": "ISO 8601 date (if known)",
    "recording_year": "integer",
    "publication_date": "ISO 8601 date (if different from recording)",
    "series_start_date": "ISO 8601 date (for series)",
    "series_end_date": "ISO 8601 date (for series)",
    "era": "enum (EarlyPeikoff | MaturePeikoff | LatePeikoff) (optional)"
  },

  "bibliographic": {
    "author": "string (for books)",
    "isbn": "string (if applicable)",
    "publisher": "string",
    "edition": "string",
    "chapter_number": "integer (for book chapters)",
    "page_range": "string (e.g., '45-67')"
  },

  "relational": {
    "part_of_series": "string (series name if applicable)",
    "series_type": "enum (Course | BookSeries | Seminar | Workshop)",
    "related_content": ["array of file_ids (conceptually related)"],
    "elaborates_on": ["array of file_ids (deeper treatment of earlier content)"],
    "summarizes": ["array of file_ids (overview of detailed content)"],
    "contradicts": ["array of file_ids (if corrections/revisions exist)"],
    "superseded_by": ["array of file_ids (if updated version exists)"],
    "companion_to": ["array of file_ids (parallel/complementary content)"]
  },

  "content_characteristics": {
    "primary_branch": "enum (Metaphysics | Epistemology | Ethics | Politics | Aesthetics | History | Applied)",
    "branches_covered": ["array of enums from primary_branch"],
    "approach": "enum (Systematic | Historical | Inductive | Deductive | Comparative | Applied)",
    "audience": "enum (Beginner | Student | Advanced | Professional | General)",
    "interaction_type": "enum (Lecture | Dialog | QA | Workshop | Debate | Interview)",
    "has_exercises": "boolean",
    "has_readings": "boolean",
    "has_homework": "boolean"
  },

  "quality_metadata": {
    "transcript_quality": "enum (Professional | AI | CommunityEdited | Draft)",
    "audio_quality": "enum (Excellent | Good | Fair | Poor)",
    "completeness": "enum (Complete | PartialBeginning | PartialEnd | Fragments)",
    "verified": "boolean (has been quality checked)",
    "notes": "string (any special notes about content/quality)"
  },

  "search_optimization": {
    "search_keywords": ["array of strings (additional search terms)"],
    "alternative_titles": ["array of strings (other ways to refer to this)"],
    "common_questions": ["array of strings (questions this answers)"],
    "learning_objectives": ["array of strings (what you'll learn)"],
    "summary": "string (brief content summary for search results)"
  },

  "technical": {
    "word_count": "integer (approximate)",
    "estimated_reading_time_minutes": "integer",
    "language_complexity": "enum (Accessible | Moderate | Technical | Expert)",
    "contains_diagrams": "boolean",
    "contains_examples": "boolean",
    "contains_case_studies": "boolean"
  }
}
```

## Category-Specific Metadata

### For Courses

```json
{
  "course_metadata": {
    "course_id": "string (unique identifier)",
    "course_full_name": "string",
    "course_abbreviation": "string (e.g., ITOE)",
    "course_type": "enum (Lecture | Seminar | Workshop | Reading)",
    "course_level": "enum (Introductory | Core | Advanced | Specialized)",
    "course_institution": "string (ARI, Lyceum, etc.)",
    "course_format": "enum (InPerson | Online | Hybrid)",
    "total_hours": "integer (course duration)",
    "credit_hours": "integer (if applicable)",
    "textbook": "string (primary text if any)",
    "supplementary_readings": ["array of strings"]
  }
}
```

### For Books

```json
{
  "book_metadata": {
    "book_id": "string",
    "book_title": "string",
    "book_author": "string",
    "book_type": "enum (Primary | Commentary | Biography | Collection)",
    "is_ayn_rand_authored": "boolean",
    "is_peikoff_authored": "boolean",
    "covers_ayn_rand": "boolean (biography/about Rand)",
    "covers_objectivism": "boolean",
    "original_publication_year": "integer",
    "this_edition_year": "integer"
  }
}
```

### For MOTM (Man of the Month)

```json
{
  "motm_metadata": {
    "session_date": "ISO 8601 date",
    "host": "string (Harry Binswanger, etc.)",
    "guest": "string (if applicable)",
    "format": "enum (Discussion | Interview | Presentation | Debate)",
    "event": "string (OCON, etc. if related)",
    "participants": ["array of strings"]
  }
}
```

### For Podcasts

```json
{
  "podcast_metadata": {
    "podcast_name": "string",
    "episode_number": "integer",
    "episode_title": "string",
    "duration_minutes": "integer",
    "podcast_host": "string",
    "guest": "string",
    "audio_url": "string (if available)",
    "show_notes": "string"
  }
}
```

## Extraction Rules by Folder Structure

### Pattern: `Courses/{CourseName}/Year{N}/Q{N}/Week{N}`

```json
{
  "classification.primary_category": "Course",
  "pedagogical_structure.course_name": "{CourseName}",
  "pedagogical_structure.course_sequence.year": "Year{N}",
  "pedagogical_structure.course_sequence.quarter": "Q{N}",
  "pedagogical_structure.course_sequence.week": "Week{N}",
  "instructional.difficulty_level": "Foundations" // if Year1
}
```

### Pattern: `Courses/{CourseName}/Class {N}`

```json
{
  "classification.primary_category": "Course",
  "pedagogical_structure.course_name": "{CourseName}",
  "pedagogical_structure.course_sequence.class_number": {N}
}
```

### Pattern: `Books/{BookTitle}/Chapter {N}`

```json
{
  "classification.primary_category": "Book",
  "classification.content_type": "BookChapter",
  "book_metadata.book_title": "{BookTitle}",
  "bibliographic.chapter_number": {N}
}
```

### Pattern: `MOTM/MOTM_{YYYY-MM-DD}_{Title}`

```json
{
  "classification.primary_category": "MOTM",
  "motm_metadata.session_date": "{YYYY-MM-DD}",
  "intellectual.title": "{Title}",
  "temporal.recording_date": "{YYYY-MM-DD}"
}
```

## Topic Taxonomy

### Philosophy Branches
- **Metaphysics**: existence, identity, consciousness, causality, free will, reality
- **Epistemology**: perception, concepts, logic, reason, truth, certainty, validation
- **Ethics**: values, virtues, happiness, egoism, life as standard
- **Politics**: rights, government, capitalism, freedom, force, law
- **Aesthetics**: art, beauty, literature, sense of life, Romanticism

### Key Concepts (Comprehensive List)

**Metaphysical:**
- Existence exists
- Law of identity (A is A)
- Law of causality
- Primacy of existence
- Metaphysically given vs. man-made
- Entity-action distinction
- Necessity vs. contingency

**Epistemological:**
- Hierarchy of knowledge
- Spiral theory of knowledge
- Context and contextual certainty
- Integration
- Objectivity
- Concept formation
- Measurement omission
- Analytic-synthetic dichotomy
- Axiomatic concepts
- Arbitrary vs. false
- Cognitive methods (induction, deduction, reduction)

**Ethical:**
- Life as the standard of value
- Rational egoism
- Cardinal values (reason, purpose, self-esteem)
- Virtues (rationality, honesty, integrity, independence, justice, productiveness, pride)
- Happiness
- Trader principle

**Political:**
- Individual rights
- Capitalism
- Limited government
- Initiation of force principle
- Property rights
- Freedom of speech

**Aesthetic:**
- Sense of life
- Art as selective re-creation of reality
- Romanticism vs. Naturalism
- Psycho-epistemology in art

## Relationship Types Explained

### Prerequisites (`builds_on`)
Content A is a prerequisite for Content B if:
- B assumes knowledge from A
- B references concepts defined in A
- B builds on arguments made in A
- Pedagogically, A should be studied before B

### Elaborations (`elaborates_on`)
Content B elaborates on Content A if:
- B provides deeper analysis of concepts introduced in A
- B gives additional examples of principles from A
- B applies concepts from A to new domains
- B is the "advanced" version of A's "intro"

### Related Content (`related_content`)
Content A and B are related if:
- They discuss the same concepts from different angles
- They address the same questions with different approaches
- They cover parallel topics in different branches
- They reference the same historical figures/debates

### Supersession (`superseded_by`)
Content A is superseded by Content B if:
- B is a revised/updated version of A
- B corrects errors in A
- B incorporates feedback/improvements over A
- Peikoff explicitly says "this replaces the earlier treatment"

## Metadata Extraction Priority

### Automatic Extraction (High Confidence)
- File path and structure
- Filename parsing
- Date patterns in filenames
- Course/series identification
- Hierarchical position (Year/Quarter/Week)

### Semi-Automatic (Requires Validation)
- Topic extraction from titles
- Instructor identification
- Related content identification
- Difficulty level inference

### Manual Enhancement (Optional but Valuable)
- Key concepts discussed
- Specific arguments presented
- Philosophers referenced
- Quality of transcript
- Learning objectives

## Validation Rules

### Required Fields
Every file MUST have:
- `core.file_id`
- `core.source_path`
- `classification.primary_category`
- `intellectual.title`

### Consistency Rules
- If `pedagogical_structure.course_sequence.year` exists, `course_name` must exist
- If `difficulty_level` is "Advanced", `prerequisites` should be populated
- If `content_type` is "QA", `interaction_type` should be "QA"
- `within_course_position` should be ≤ `total_course_length`

### Inference Rules
- First week of first quarter of first year → `difficulty_level = "Foundations"`
- Course name contains "Advanced" → `difficulty_level = "Advanced"`
- Course name contains "Introduction" → `difficulty_level = "Introductory"`
- Filename contains "Office Hour" → `content_type = "OfficeHour"`

## Example Complete Metadata Records

### Example 1: Structured Course Lecture

```json
{
  "core": {
    "file_id": "gemini-file-abc123",
    "source_path": "Courses/Objectivism Seminar - Foundations/Year1/Q1/Week4.txt",
    "filename": "Objectivism Seminar - Foundations - Year 1 - Q1 - Week 4.txt"
  },
  "classification": {
    "primary_category": "Course",
    "content_type": "Lecture",
    "format": "Transcript"
  },
  "intellectual": {
    "title": "The Foundations of the Objectivist Ethics – Life as the Standard of Value",
    "topics": ["ethics", "standard of value", "life", "values"],
    "key_concepts": ["life as standard", "value", "goal", "conditional"],
    "philosophers_discussed": ["Aristotle", "Kant"]
  },
  "instructional": {
    "instructor": "Leonard Peikoff",
    "difficulty_level": "Foundations",
    "prerequisites": ["Week 1", "Week 2", "Week 3"],
    "builds_on": ["file-id-week1", "file-id-week2", "file-id-week3"]
  },
  "pedagogical_structure": {
    "course_name": "Objectivism Seminar - Foundations",
    "course_sequence": {
      "year": "Year1",
      "quarter": "Q1",
      "week": "Week4"
    },
    "curriculum_stage": "Development",
    "within_course_position": 4
  },
  "relational": {
    "part_of_series": "Objectivism Seminar - Foundations",
    "elaborates_on": ["file-id-ethics-intro"],
    "prepares_for": ["file-id-week5-cardinal-values"]
  },
  "content_characteristics": {
    "primary_branch": "Ethics",
    "branches_covered": ["Ethics", "Epistemology"],
    "approach": "Systematic",
    "audience": "Student"
  }
}
```

### Example 2: Book Chapter

```json
{
  "core": {
    "file_id": "gemini-file-def456",
    "source_path": "Books/Leonard Peikoff - Understanding Objectivism/Lecture_03.txt"
  },
  "classification": {
    "primary_category": "Book",
    "content_type": "BookChapter"
  },
  "intellectual": {
    "title": "Lecture Three: The Hierarchy and Spiral of Knowledge",
    "topics": ["epistemology", "hierarchy", "spiral theory", "integration"],
    "key_concepts": ["spiral theory of knowledge", "hierarchy", "context", "integration", "the true is the whole"],
    "key_terms_defined": ["spiral theory of knowledge", "hierarchy principle"]
  },
  "instructional": {
    "instructor": "Leonard Peikoff",
    "difficulty_level": "Advanced",
    "prerequisites": ["Lecture 1", "Lecture 2"]
  },
  "bibliographic": {
    "author": "Leonard Peikoff",
    "book_title": "Understanding Objectivism",
    "chapter_number": 3,
    "publisher": "NAL"
  },
  "book_metadata": {
    "is_peikoff_authored": true,
    "covers_objectivism": true,
    "original_publication_year": 2012
  },
  "content_characteristics": {
    "primary_branch": "Epistemology",
    "approach": "Systematic",
    "audience": "Advanced"
  }
}
```

### Example 3: MOTM Discussion

```json
{
  "core": {
    "file_id": "gemini-file-ghi789",
    "source_path": "MOTM/MOTM_2023-07-09_OCON-Retrospective.txt"
  },
  "classification": {
    "primary_category": "MOTM",
    "content_type": "Discussion"
  },
  "intellectual": {
    "title": "OCON 2023 Retrospective",
    "topics": ["conference review", "objectivist conferences", "recent developments"]
  },
  "motm_metadata": {
    "session_date": "2023-07-09",
    "host": "Harry Binswanger",
    "format": "Discussion",
    "event": "OCON 2023"
  },
  "temporal": {
    "recording_date": "2023-07-09",
    "recording_year": 2023
  },
  "content_characteristics": {
    "approach": "Applied",
    "audience": "General",
    "interaction_type": "Discussion"
  }
}
```

## Usage in Queries

### Semantic Search with Metadata Filters

```python
# Find foundational ethics content
results = corpus.query(
    query="What is the standard of value?",
    metadata_filter={
        "content_characteristics.primary_branch": "Ethics",
        "instructional.difficulty_level": "Foundations"
    }
)

# Find advanced epistemology from Peikoff
results = corpus.query(
    query="How does knowledge form hierarchies?",
    metadata_filter={
        "instructional.instructor": "Leonard Peikoff",
        "content_characteristics.primary_branch": "Epistemology",
        "instructional.difficulty_level": ["Advanced", "Expert"]
    }
)

# Get all Year 1 Q1 content
results = corpus.query(
    query="*",  # Match all
    metadata_filter={
        "pedagogical_structure.course_sequence.year": "Year1",
        "pedagogical_structure.course_sequence.quarter": "Q1"
    }
)
```

## Maintenance & Updates

### When to Update Metadata
- New courses are added to library
- Course structures change
- Relationships between content are discovered
- Quality improvements (better transcripts)
- User feedback reveals missing connections

### Metadata Evolution
The schema supports extension. New fields can be added without breaking existing metadata. Use semantic versioning for schema versions.

### Quality Assurance
- Regular validation checks
- Community feedback integration
- Automated consistency checking
- Periodic metadata enrichment passes
