# Objectivism Library Semantic Search System

## Overview

A comprehensive semantic search system for the Objectivism Library using Google's Gemini File API. This system preserves the intellectual and pedagogical structure of your library while enabling powerful semantic search capabilities.

## What This System Does

### Core Capabilities

1. **Semantic Search**: Search by concept, not just keywords
   - "How does knowledge deepen over time?" → Finds Spiral Theory discussions
   - "Relationship between reason and values" → Finds relevant ethics content

2. **Structure-Aware Queries**: Leverage your library's organization
   - Search within specific courses, years, quarters
   - Find foundational vs. advanced discussions
   - Trace concept evolution through curriculum

3. **Cross-Reference Intelligence**:
   - Compare explanations across different sources
   - Find related discussions automatically
   - Track prerequisite chains

4. **Synthesis & Analysis**:
   - Generate comprehensive answers from multiple sources
   - Create synthesis documents (like the Spiral Theory doc)
   - Track how Peikoff's explanations evolved over time

## Architecture

```
Your Library (File System)
         ↓
    Metadata Extractor (Preserves structure & relationships)
         ↓
    Gemini File API Corpus (Searchable semantic index)
         ↓
    Query Interface (Natural language + filters)
         ↓
    Results (With citations, context, synthesis)
```

## Project Structure

```
objectivism-library-semantic-search/
├── README.md (this file)
├── METADATA_SCHEMA.md (Complete metadata specification)
├── IMPLEMENTATION_PLAN.md (Detailed implementation guide)
├── config/
│   ├── library_config.json (Library structure configuration)
│   └── gemini_config.example.json (API configuration template)
├── src/
│   ├── 01_scan_library.py (Extract structure & create metadata)
│   ├── 02_upload_to_gemini.py (Upload files with metadata)
│   ├── 03_query_interface.py (Search and query system)
│   ├── 04_synthesis_engine.py (Multi-source synthesis)
│   └── utils/
│       ├── metadata_extractor.py (Smart metadata extraction)
│       ├── structure_parser.py (Parse folder hierarchies)
│       └── gemini_client.py (Gemini API wrapper)
├── examples/
│   ├── example_queries.py (Sample queries to demonstrate capabilities)
│   └── example_workflows.py (Complete usage workflows)
├── docs/
│   ├── QUERY_GUIDE.md (How to query effectively)
│   └── METADATA_GUIDE.md (Understanding the metadata)
└── tests/
    ├── test_metadata_extraction.py
    └── test_queries.py
```

## Quick Start

### Prerequisites

```bash
pip install google-generativeai python-dotenv pathlib
```

### Setup

1. **Configure your API key**:
```bash
export GEMINI_API_KEY="your-key-here"
```

2. **Scan your library**:
```bash
python src/01_scan_library.py
```

3. **Upload to Gemini** (one-time setup):
```bash
python src/02_upload_to_gemini.py
```

4. **Start querying**:
```bash
python src/03_query_interface.py
```

## Example Queries

### Semantic Search
```python
from src.query_interface import ObjectivismLibrary

library = ObjectivismLibrary()

# Natural language concept search
results = library.search("How does understanding deepen through repeated learning?")

# With structure filters
results = library.search(
    "concept formation",
    filters={"course": "ITOE", "difficulty": "advanced"}
)
```

### Structure-Based Navigation
```python
# Find all Year 1, Quarter 1 content
foundational = library.get_by_structure(year="Year1", quarter="Q1")

# Get a specific course's progression
itoe_progression = library.get_course_sequence("ITOE Advanced Topics")
```

### Concept Evolution Tracking
```python
# See how a concept is explained across the curriculum
evolution = library.trace_concept_evolution("objectivity")
# Returns: Foundations → Intermediate → Advanced → Cross-course synthesis
```

### Comparative Analysis
```python
# Compare how different courses explain the same concept
comparison = library.compare_explanations(
    concept="free will",
    source1="Objectivism Through Induction",
    source2="Advanced Seminars on Objectivism"
)
```

### Synthesis Generation
```python
# Generate comprehensive synthesis (like Spiral Theory doc)
synthesis = library.generate_synthesis(
    concept="validation of axioms",
    include_sources=True,
    format="markdown"
)
```

## Key Features

### 1. Intelligent Metadata
Every file gets rich metadata including:
- Pedagogical structure (Year/Quarter/Week or Class number)
- Topic and subtopics
- Difficulty level
- Prerequisites
- Related content
- Key concepts discussed
- Philosophers referenced

### 2. Preserved Organization
Your careful folder structure becomes searchable metadata:
- Course hierarchies maintained
- Curriculum sequences preserved
- Pedagogical relationships tracked

### 3. Cross-Reference Discovery
System automatically identifies:
- Related discussions across courses
- Prerequisite knowledge chains
- Later elaborations of earlier concepts

### 4. Multiple Search Modes
- **Semantic**: Search by concept/meaning
- **Structural**: Navigate by course/year/topic
- **Hybrid**: Combine semantic + structural filters
- **Evolutionary**: Track concept development over time

## Implementation Timeline

### Phase 1: Setup & Scanning (Day 1)
- Configure environment
- Scan library structure
- Extract metadata
- Generate catalog

### Phase 2: Upload & Index (Day 1-2)
- Upload files to Gemini
- Create corpus with metadata
- Verify upload completeness
- Test basic queries

### Phase 3: Query Interface (Day 2-3)
- Build query system
- Implement filters
- Add synthesis capabilities
- Create examples

### Phase 4: Advanced Features (Day 3-5)
- Concept evolution tracking
- Comparative analysis
- Automated synthesis
- Integration tools

## Benefits Over Traditional Search

| Traditional Search | Semantic Search with This System |
|-------------------|----------------------------------|
| Keyword matching only | Concept-based understanding |
| No structure awareness | Leverages pedagogical organization |
| Single file at a time | Cross-course synthesis |
| Manual cross-referencing | Automatic relationship discovery |
| Static results | Contextual, synthesized answers |

## Future Enhancements

- **Visual concept mapping**: Graph visualization of concept relationships
- **Spaced repetition integration**: Track what you've studied
- **Note-taking integration**: Link your notes to library content
- **Timeline view**: See Peikoff's teaching evolution chronologically
- **Export to Obsidian/Roam**: Create knowledge graph exports

## Support & Documentation

See detailed documentation in:
- `METADATA_SCHEMA.md` - Complete metadata specification
- `IMPLEMENTATION_PLAN.md` - Step-by-step implementation
- `docs/QUERY_GUIDE.md` - Advanced query techniques
- `docs/METADATA_GUIDE.md` - Understanding the metadata system

## Philosophy

This system respects the intellectual structure of your library. Your folder organization represents years of careful curation and pedagogical insight. We preserve that structure as semantic metadata, making it searchable and actionable while adding the power of concept-based search.

The goal: **Make the wisdom in your library as accessible as asking a question.**
