# Quick Start Guide

Get your semantic search system up and running in 30 minutes!

## Prerequisites

1. **Python 3.9+** installed
2. **Gemini API Key** from https://ai.google.dev/
3. **Your Objectivism Library** at `/Volumes/U32 Shadow/Objectivism Library`

## Step 1: Install Dependencies (2 minutes)

```bash
cd ~/Downloads/objectivism-library-semantic-search

# Install required packages
pip install google-generativeai>=0.3.0
pip install python-dotenv
pip install tqdm  # For progress bars
```

## Step 2: Set Up API Key (1 minute)

```bash
# Set your Gemini API key
export GEMINI_API_KEY="your-api-key-here"

# Or add to your shell profile (~/.zshrc or ~/.bashrc)
echo 'export GEMINI_API_KEY="your-api-key-here"' >> ~/.zshrc
```

## Step 3: Scan Your Library (5-10 minutes)

```bash
cd src

# Scan the library and create catalog
python 01_scan_library.py --verbose

# This creates: ../data/library_catalog.json
```

**What this does:**
- Scans all .txt files in your library
- Extracts metadata from folder structure
- Identifies courses, books, MOTM sessions
- Parses Year/Quarter/Week organization
- Creates a catalog with ~1000-2000 entries

**Expected output:**
```
Scanning library: /Volumes/U32 Shadow/Objectivism Library
Processed 1247 files...
Scan complete!

CATALOG STATISTICS
Files by Category:
  Course              : 856
  Book                : 234
  MOTM                :  89
  ...
```

## Step 4: Upload to Gemini (1-3 hours)

```bash
# Upload files to Gemini File API
python 02_upload_to_gemini.py --batch-size 100 --resume

# This creates: ../data/upload_state_objectivism-library-v1.json
```

**What this does:**
- Uploads each file to Gemini
- Attaches all metadata as searchable fields
- Creates a corpus: `objectivism-library-v1`
- Saves progress every 100 files (resumable if interrupted)

**Progress:**
```
Uploading 1247 files to Gemini...
Progress: 100/1247 (8.0%)
Progress: 200/1247 (16.0%)
...
Successfully uploaded: 1247
Failed uploads: 0
```

**Time estimate:**
- Small library (<500 files): 30-60 min
- Medium (500-1500): 1-3 hours
- Large (1500+): 3-6 hours

**If interrupted:** Just run with `--resume` flag and it will continue where it left off.

## Step 5: Start Querying! (Instant)

### Interactive Mode

```bash
python 03_query_interface.py --interactive
```

Then type queries:
```
> search spiral theory of knowledge
> ask What is the relationship between hierarchy and context?
> trace free will
> quit
```

### Command Line

```bash
# Simple search
python 03_query_interface.py --query "How does knowledge deepen over time?"

# Ask a question (with synthesis from multiple sources)
python 03_query_interface.py --question "What are the cardinal values?"

# Trace concept evolution
python 03_query_interface.py --trace "objectivity"

# Generate comprehensive synthesis
python 03_query_interface.py --synthesize "spiral theory of knowledge"
```

### Python Script

```python
from query_interface import ObjectivismLibrary

# Initialize
library = ObjectivismLibrary()

# Search
results = library.search("concept formation")
for r in results:
    print(r['metadata']['intellectual.title'])

# Ask question with synthesis
answer = library.ask_question("How do you validate axioms?")
print(answer)

# Trace concept across curriculum
evolution = library.trace_concept_evolution("free will")
for source in evolution:
    print(f"{source['metadata']['difficulty_level']}: {source['metadata']['title']}")
```

## Example Queries to Try

### Conceptual Questions
```bash
python 03_query_interface.py --question "What is the spiral theory of knowledge?"
python 03_query_interface.py --question "How does understanding deepen through iteration?"
python 03_query_interface.py --question "What's the relationship between reason and values?"
```

### Structural Navigation
```python
from query_interface import ObjectivismLibrary

library = ObjectivismLibrary()

# Get all Year 1, Q1 lectures
week1 = library.get_by_structure(year="Year1", quarter="Q1", week="Week1")

# Browse a specific course
itoe = library.search("*", filters={"course_name": "ITOE Advanced Topics"})
```

### Concept Evolution
```bash
# See how Peikoff explains a concept from basic to advanced
python 03_query_interface.py --trace "causality"
python 03_query_interface.py --trace "concept formation"
python 03_query_interface.py --trace "egoism"
```

### Synthesis Generation
```bash
# Generate comprehensive synthesis doc (like we did for Spiral Theory)
python 03_query_interface.py --synthesize "validation of axioms"
python 03_query_interface.py --synthesize "cardinal values"

# Output saved to: ../output/validation_of_axioms_synthesis.md
```

## Verification

To verify everything is working:

```bash
cd examples
python example_queries.py
```

This runs 8 example queries and shows you what the system can do.

## Troubleshooting

### "Corpus not found"
**Solution:** Make sure Step 4 (upload) completed successfully. Check:
```bash
cat ../data/upload_state_objectivism-library-v1.json
```

### "GEMINI_API_KEY not found"
**Solution:** Set the environment variable:
```bash
export GEMINI_API_KEY="your-key-here"
```

### Poor search results
**Solution:**
- Be more specific in your query
- Use filters to narrow scope
- Try different phrasings

### Upload taking too long
**Solution:**
- Reduce batch size: `--batch-size 50`
- Check internet connection
- Use `--resume` to continue if interrupted

## Next Steps

Once you have the basics working:

1. **Explore the library** - Try different queries and see what you discover
2. **Run examples** - `python examples/example_queries.py`
3. **Read the docs** - See `IMPLEMENTATION_PLAN.md` for advanced features
4. **Customize** - Modify scripts for your specific needs

## Getting Help

- Read `README.md` for complete overview
- Check `IMPLEMENTATION_PLAN.md` for detailed documentation
- Review `METADATA_SCHEMA.md` to understand the metadata structure
- Look at `examples/` for usage patterns

## What You Can Do Now

With your semantic search system running, you can:

✓ **Search by concept** - Not just keywords
✓ **Navigate structure** - By year, quarter, course
✓ **Trace evolution** - See how concepts develop
✓ **Compare sources** - Different explanations side-by-side
✓ **Generate syntheses** - Comprehensive documents automatically
✓ **Ask questions** - Get answers synthesized from multiple sources

**The wisdom in your library is now accessible through natural language!**

## Performance Notes

- **Query speed**: 1-3 seconds typically
- **Synthesis generation**: 5-15 seconds
- **Accuracy**: Semantic search finds relevant content even with different wording
- **Cost**: ~$0.01-0.05 per 1000 queries (Gemini pricing)

## Maintenance

### Adding New Content

When you acquire new lectures/books:

```bash
# 1. Add files to your library folder
# 2. Re-scan
python src/01_scan_library.py

# 3. Upload new files
python src/02_upload_to_gemini.py --resume

# Done! New content is immediately searchable
```

### Updating Metadata

If you want to enrich metadata:

```bash
# Edit: data/library_catalog.json
# Then re-upload:
python src/02_upload_to_gemini.py --catalog data/library_catalog.json
```

---

**You're all set! Start exploring your library semantically. Enjoy!**
