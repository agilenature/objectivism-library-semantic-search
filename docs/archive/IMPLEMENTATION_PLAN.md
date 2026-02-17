# Implementation Plan: Objectivism Library Semantic Search

## Overview

This document provides a detailed, step-by-step implementation plan for building the semantic search system for your Objectivism Library using Google's Gemini File API.

## Prerequisites

### Technical Requirements
- Python 3.9+
- Google Cloud account with Gemini API access
- Gemini API key
- ~20GB disk space for processing
- Stable internet connection (for upload phase)

### Python Packages
```bash
pip install google-generativeai>=0.3.0
pip install python-dotenv>=1.0.0
pip install pathlib
pip install tqdm  # Progress bars
pip install pandas  # Data analysis (optional)
pip install pytest  # Testing (optional)
```

### API Setup
1. Go to https://ai.google.dev/
2. Get your Gemini API key
3. Set environment variable:
```bash
export GEMINI_API_KEY="your-key-here"
```

## Implementation Phases

### Phase 1: Library Scanning & Metadata Extraction (Estimated: 2-3 hours)

#### 1.1 Configure Library Path

**File**: `config/library_config.json`
```json
{
  "library_root": "/Volumes/U32 Shadow/Objectivism Library",
  "excluded_patterns": [".claude", ".DS_Store", ".git"],
  "file_extensions": [".txt"],
  "scan_depth": 10,
  "output_catalog": "data/library_catalog.json"
}
```

#### 1.2 Run Library Scanner

**Script**: `src/01_scan_library.py`

**What it does**:
- Recursively scans your library folder
- Identifies file patterns (Course/Year/Quarter vs. Class vs. Books)
- Extracts metadata from folder structure
- Parses filenames for additional metadata
- Generates initial catalog

**Expected output**: `data/library_catalog.json` with ~1000-2000 entries

**Run**:
```bash
python src/01_scan_library.py --verbose
```

**Validation**:
```bash
# Check catalog
python -c "import json; print(len(json.load(open('data/library_catalog.json'))['files']))"
# Should show total file count

# Inspect sample
python -c "import json; import pprint; pprint.pprint(json.load(open('data/library_catalog.json'))['files'][0])"
```

#### 1.3 Metadata Enrichment (Optional but Recommended)

**Script**: `src/utils/metadata_enricher.py`

**What it does**:
- Infers difficulty levels from course names
- Identifies prerequisites based on curriculum position
- Discovers related content by topic similarity
- Extracts key concepts from titles

**Run**:
```bash
python src/utils/metadata_enricher.py --input data/library_catalog.json --output data/library_catalog_enriched.json
```

#### 1.4 Manual Review (Optional)

Export catalog to CSV for review:
```bash
python src/utils/export_catalog.py --format csv --output data/catalog_review.csv
```

Review in spreadsheet, make corrections, re-import:
```bash
python src/utils/import_catalog.py --input data/catalog_corrected.csv --output data/library_catalog_final.json
```

### Phase 2: Upload to Gemini File API (Estimated: 4-6 hours)

**Time estimate factors**:
- Number of files (~1000-2000)
- File sizes (mostly <500KB each)
- Upload speed (~1 file/second typical)
- API rate limits (handled automatically with retries)

#### 2.1 Initialize Gemini Corpus

**Script**: `src/02_upload_to_gemini.py`

**Key decisions**:
- **Corpus name**: `objectivism-library-{version}` (e.g., `objectivism-library-v1`)
- **Chunking strategy**: Let Gemini handle (recommended) OR manual chunks (advanced)
- **Batch size**: Upload 100 files, verify, repeat

**Run** (with progress tracking):
```bash
python src/02_upload_to_gemini.py --catalog data/library_catalog_final.json --batch-size 100 --resume
```

**Features**:
- **Progress saving**: Saves state every 100 files
- **Resume capability**: Can restart if interrupted
- **Verification**: Checks each upload succeeded
- **Error handling**: Retries failed uploads with exponential backoff

#### 2.2 Create Corpus Documents with Metadata

For each file:
1. Upload file to Gemini
2. Get file URI
3. Create document in corpus
4. Attach all metadata as custom_metadata
5. Link file URI to document
6. Verify

**Metadata attachment example**:
```python
document = corpus.create_document(
    name=f"doc-{safe_filename}",
    display_name=metadata["intellectual"]["title"],
    custom_metadata=[
        {"key": "category", "string_value": metadata["classification"]["primary_category"]},
        {"key": "course_name", "string_value": metadata["pedagogical_structure"]["course_name"]},
        {"key": "difficulty", "string_value": metadata["instructional"]["difficulty_level"]},
        # ... all metadata fields
    ]
)
```

#### 2.3 Build Relationship Graph

After all files uploaded:
```bash
python src/utils/build_relationships.py --corpus objectivism-library-v1
```

**What it does**:
- Creates prerequisite chains (Week1 → Week2 → Week3)
- Identifies related content (similar topics)
- Maps elaboration relationships (intro → advanced)
- Stores in `data/relationship_graph.json`

#### 2.4 Verification

```bash
python src/utils/verify_upload.py --corpus objectivism-library-v1 --catalog data/library_catalog_final.json
```

**Checks**:
- All files uploaded successfully
- Metadata attached correctly
- Documents searchable
- Sample queries return expected results

**Expected output**:
```
✓ Total files in catalog: 1247
✓ Successfully uploaded: 1247
✓ Failed uploads: 0
✓ Metadata fields attached: avg 28.3 per document
✓ Sample query test: PASSED
```

### Phase 3: Query Interface Development (Estimated: 3-4 hours)

#### 3.1 Basic Query Interface

**Script**: `src/03_query_interface.py`

**Core class**: `ObjectivismLibrary`

**Methods implemented**:

```python
class ObjectivismLibrary:
    def __init__(self, corpus_name):
        """Initialize with your corpus"""

    def search(self, query, filters=None, limit=10):
        """Semantic search with optional metadata filters"""

    def get_by_structure(self, **kwargs):
        """Navigate by folder structure (year, quarter, course, etc.)"""

    def get_document(self, file_id):
        """Retrieve full document with metadata"""

    def get_related(self, file_id, relationship_type="related"):
        """Find related documents"""
```

**Test**:
```bash
python src/03_query_interface.py --test
```

#### 3.2 Advanced Query Features

**File**: `src/04_synthesis_engine.py`

**Methods**:

```python
class SynthesisEngine:
    def trace_concept_evolution(self, concept, chronological=True):
        """Show how concept is explained across curriculum"""

    def compare_explanations(self, concept, source1_filter, source2_filter):
        """Compare different explanations of same concept"""

    def generate_synthesis(self, concept, sources=None, format="markdown"):
        """Generate comprehensive synthesis document"""

    def find_prerequisites(self, topic):
        """What should you know before studying this?"""

    def find_applications(self, principle):
        """Where is this principle applied?"""
```

#### 3.3 Command-Line Interface

**Script**: `src/cli.py`

**Usage**:
```bash
# Simple search
./src/cli.py search "How does knowledge deepen?"

# With filters
./src/cli.py search "concept formation" --course "ITOE" --difficulty "advanced"

# Navigate structure
./src/cli.py navigate --year Year1 --quarter Q1

# Trace concept
./src/cli.py trace "free will"

# Compare sources
./src/cli.py compare "objectivity" --source1 "ITOE" --source2 "Objectivism Through Induction"

# Generate synthesis
./src/cli.py synthesize "spiral theory of knowledge" --output ~/Downloads/synthesis.md
```

#### 3.4 Python API Usage

**Example script**:
```python
from src.query_interface import ObjectivismLibrary

# Initialize
library = ObjectivismLibrary("objectivism-library-v1")

# Semantic search
results = library.search("What is the relationship between hierarchy and context?")
for result in results:
    print(f"{result.title} ({result.course_name})")
    print(result.excerpt)
    print()

# Filtered search
foundational_ethics = library.search(
    "values and virtues",
    filters={
        "content_characteristics.primary_branch": "Ethics",
        "instructional.difficulty_level": "Foundations"
    }
)

# Navigate structure
week4_content = library.get_by_structure(
    course_name="Objectivism Seminar - Foundations",
    year="Year1",
    quarter="Q1",
    week="Week4"
)

# Trace concept evolution
evolution = library.trace_concept_evolution("objectivity")
print(f"Concept appears in {len(evolution)} sources:")
for source in evolution:
    print(f"- {source.title} ({source.difficulty_level})")
```

### Phase 4: Advanced Features (Estimated: 2-4 hours)

#### 4.1 Concept Evolution Tracker

**What it does**:
- Takes a philosophical concept (e.g., "free will")
- Finds all discussions across library
- Orders by pedagogical sequence
- Shows progression from intro → advanced
- Highlights key distinctions/elaborations at each stage

**Output format**:
```markdown
# Evolution of "Free Will" Across the Curriculum

## Foundational Introduction (Year 1, Q2, Week 3)
- **Source**: Objectivism Seminar - Foundations
- **Level**: Foundations
- **Key Points**:
  - Introduction to volition
  - Free will as axiom of consciousness
  - Self-evident nature

## Deeper Analysis (ITOE - Class 05)
- **Source**: ITOE
- **Level**: Intermediate
- **Key Points**:
  - Free will and concept formation
  - Volitional nature of focus
  - Connection to validation

## Advanced Integration (Advanced Seminars - Lesson 04)
- **Source**: Advanced Seminars on Objectivism
- **Level**: Advanced
- **Key Points**:
  - Free will vs. determinism in depth
  - Causality and volition reconciled
  - Metaphysical analysis
```

#### 4.2 Comparative Analysis Tool

**What it does**:
- Takes concept + two sources
- Retrieves both explanations
- Uses Gemini to compare/contrast
- Highlights unique insights from each
- Shows complementary vs. contradictory elements

**Example**:
```bash
python src/cli.py compare "validation of axioms" \
  --source1 "Objectivism Through Induction" \
  --source2 "ITOE"
```

**Output**:
```markdown
# Comparative Analysis: Validation of Axioms

## Common Ground
Both sources emphasize:
- Axioms are self-evident
- Validation is performative not deductive
- Stolen concept fallacy in denying them

## Unique to "Objectivism Through Induction"
- Historical analysis (Aristotle → Rand)
- Inductive approach emphasis
- Role of axioms in system-building

## Unique to "ITOE"
- Technical epistemological detail
- Concept formation connection
- Analytic-synthetic dichotomy tie-in

## Complementary Insights
- OTI provides historical context
- ITOE provides technical precision
- Together: complete understanding
```

#### 4.3 Synthesis Document Generator

**Like what we did for Spiral Theory, automated:**

```bash
python src/cli.py synthesize "spiral theory of knowledge" \
  --include-all-sources \
  --format markdown \
  --output ~/Downloads/spiral_theory_synthesis.md
```

**Process**:
1. Search for all references to concept
2. Extract relevant passages with context
3. Use Gemini to organize by themes
4. Generate structure (definition, characteristics, applications, etc.)
5. Include citations and source references
6. Create table of contents
7. Add visual diagrams if applicable

#### 4.4 Prerequisite Mapper

**What it does**:
- For any topic, identify what you need to know first
- Generate learning path from foundations up
- Suggest reading order

**Example**:
```python
learning_path = library.generate_learning_path("concept formation")
```

**Output**:
```
Learning Path for "Concept Formation"

Prerequisites (Study first):
1. Perception and the senses (Metaphysics foundations)
2. Consciousness as identification (Epistemology basics)
3. Abstraction from concretes (Basic epistemology)

Core Content (Main study):
1. ITOE - Lecture 4: Units and Measurement
2. ITOE - Lecture 5: Concept Formation Process
3. Objectivism Through Induction - Lesson 7: The Theory of Concepts

Advanced (Deeper understanding):
1. ITOE Advanced Topics - Implicit vs. Explicit
2. Advanced Seminars - Concept Formation Details

Related Applications:
1. Ethics (concept of value)
2. Politics (concept of rights)
```

### Phase 5: Testing & Validation (Estimated: 2-3 hours)

#### 5.1 Unit Tests

**File**: `tests/test_metadata_extraction.py`

Test cases:
- Folder pattern recognition
- Filename parsing
- Metadata inference
- Relationship discovery

**Run**:
```bash
pytest tests/test_metadata_extraction.py -v
```

#### 5.2 Integration Tests

**File**: `tests/test_queries.py`

Test scenarios:
- Semantic search returns relevant results
- Metadata filters work correctly
- Relationship traversal functions
- Synthesis generation produces valid output

#### 5.3 Quality Assurance

**Manual test queries** (in `tests/qa_test_queries.txt`):
```
1. "What is the spiral theory of knowledge?"
   Expected: Understanding Objectivism, Unity in Epistemology, etc.

2. "How do you validate axioms?"
   Expected: Objectivism Through Induction, ITOE

3. "What are the cardinal values?"
   Expected: Ethics courses, Year 1 Q1 Week 6-8

4. [Search with filter] "free will" + difficulty=Foundations
   Expected: Only foundational sources

5. [Navigation] Get Year1 Q1 Week1
   Expected: Specific first-week lectures
```

**Validation script**:
```bash
python tests/run_qa_tests.py --queries tests/qa_test_queries.txt --report tests/qa_results.html
```

### Phase 6: Documentation & Examples (Estimated: 1-2 hours)

#### 6.1 Query Guide

**File**: `docs/QUERY_GUIDE.md`

Sections:
- Basic queries
- Using filters effectively
- Combining semantic + structural search
- Advanced query patterns
- Common use cases with examples

#### 6.2 Example Workflows

**File**: `examples/example_workflows.py`

Workflows:
- "I'm new to Objectivism, where do I start?"
- "I want to understand concept formation deeply"
- "Compare Peikoff's early vs. late explanations"
- "Generate study guide for OCON talk"

#### 6.3 Jupyter Notebook Examples

**File**: `examples/interactive_examples.ipynb`

Interactive demos:
- Basic search
- Filtered queries
- Concept evolution visualization
- Comparative analysis
- Synthesis generation

### Phase 7: Deployment & Maintenance (Ongoing)

#### 7.1 Initial Deployment

1. Complete upload
2. Run verification tests
3. Document corpus version
4. Create backup of catalog/metadata

#### 7.2 Usage Monitoring

Track:
- Most common queries
- Query success rates
- Response times
- User feedback

#### 7.3 Maintenance Schedule

**Weekly**:
- Review query logs
- Note failed searches
- Identify missing relationships

**Monthly**:
- Add newly acquired content
- Enrich metadata based on usage
- Update relationship graph

**Quarterly**:
- Major metadata enrichment pass
- Review and improve extraction rules
- Update documentation

## Troubleshooting Guide

### Common Issues

#### Issue 1: Upload Failures

**Symptoms**: Files fail to upload, timeout errors

**Solutions**:
- Check network connectivity
- Reduce batch size (--batch-size 50)
- Verify API key is valid
- Check Gemini API status
- Use --resume flag to continue

#### Issue 2: Metadata Not Searchable

**Symptoms**: Filters don't work, metadata missing in results

**Solutions**:
- Verify metadata attached during upload
- Check field names match schema
- Re-upload with corrected metadata
- Validate JSON structure

#### Issue 3: Poor Search Results

**Symptoms**: Irrelevant results, missing obvious matches

**Solutions**:
- Improve query phrasing (be more specific)
- Use filters to narrow scope
- Check if expected content is uploaded
- Verify file content is clean (no OCR errors)
- Consider adding search_keywords to metadata

#### Issue 4: Slow Queries

**Symptoms**: Queries take >10 seconds

**Solutions**:
- Add more specific filters
- Reduce results_count limit
- Check network latency
- Verify corpus not overloaded
- Consider corpus sharding for very large libraries

## Performance Expectations

### Upload Phase
- **Small library** (<500 files): 30-60 minutes
- **Medium library** (500-1500 files): 1-3 hours
- **Large library** (1500+ files): 3-6 hours

### Query Performance
- **Simple semantic search**: <2 seconds
- **Filtered search**: <3 seconds
- **Synthesis generation**: 5-15 seconds
- **Concept evolution**: 10-30 seconds

### Resource Usage
- **Storage**: Gemini-hosted (no local storage required)
- **API costs**: ~$0.01-0.05 per 1000 queries (Gemini pricing)
- **Bandwidth**: Upload ~500MB-2GB (one-time)

## Success Metrics

### Phase 1 Success Criteria
- ✓ All files scanned
- ✓ Metadata extracted for >95% of files
- ✓ Catalog passes validation
- ✓ Manual spot-check confirms accuracy

### Phase 2 Success Criteria
- ✓ All files uploaded to Gemini
- ✓ Corpus created successfully
- ✓ Metadata searchable
- ✓ Sample queries return results

### Phase 3 Success Criteria
- ✓ Query interface functional
- ✓ Filters work correctly
- ✓ Results include proper citations
- ✓ Navigation by structure works

### Phase 4 Success Criteria
- ✓ Advanced features operational
- ✓ Synthesis generation produces quality output
- ✓ Concept evolution tracking accurate
- ✓ Comparative analysis insightful

### Overall Success
- Can answer any conceptual question about Objectivism from your library
- Results are relevant and properly sourced
- Saves significant time vs. manual search
- Discovers connections you wouldn't have found manually

## Next Steps After Implementation

1. **Daily Use**: Integrate into your study workflow
2. **Feedback Loop**: Note what works, what doesn't
3. **Metadata Enrichment**: Continuously improve as you use it
4. **Share**: Consider sharing methodology with Objectivist community
5. **Expand**: Add new content as acquired
6. **Innovate**: Build on this foundation (visualization, integration with note-taking, etc.)

## Support & Community

- **Issues**: Document in `issues/` folder
- **Improvements**: Track in `improvements.md`
- **Contributions**: If others want to help, use git for collaboration

## Conclusion

This implementation transforms your carefully curated library from a file system into an intelligent knowledge base. The folder structure you've built becomes searchable metadata, and semantic search makes the wisdom within accessible through natural language.

Estimated total implementation time: **15-25 hours** across 1-2 weeks.

The result: **A philosophical research assistant that knows your entire library.**
