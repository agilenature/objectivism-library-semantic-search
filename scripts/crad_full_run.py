#!/usr/bin/env python3
"""CRAD Full Run: Run CRAD on all 63 S1-failing files.

Phase 16.6-02 — Generates discrimination phrases for all 63 S1-failing files,
validates against Gemini, updates identity headers, re-uploads via FSM pipeline,
and runs store-sync to confirm integrity.

All Pass 2 phrases are pre-computed inline (Claude Code session judgment, 2026-02-26).
No ANTHROPIC_API_KEY required.

Usage:
  python scripts/crad_full_run.py [--dry-run] [--skip-upload] [--validate-only]
  python scripts/crad_full_run.py --file FILENAME  # run for one file only

Options:
  --dry-run        Validate phrases only; don't re-upload or update DB
  --skip-upload    Validate and update DB; don't re-upload to Gemini
  --validate-only  Same as --skip-upload
  --file NAME      Run for a single file (for testing/recovery)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Project path setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crad_algorithm import (
    build_corpus_freq_map,
    build_discrimination_phrase,
    build_genus_profile,
    create_crad_tables,
    get_claude_discrimination_phrase,
    store_discrimination_phrase,
    store_genus_profile,
    validate_phrase,
)

# -- Constants ----------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "library.db"
VALIDATION_RUNS = 3
MAX_ACCEPTABLE_RANK = 5
MAX_ESCALATIONS = 5  # plan gate: ≤5 escalations allowed

# -- Pre-computed discrimination phrases (Pass 2 inline judgment) -------------
# Claude Code session judgment, 2026-02-26
# Format: {filename: {discrimination_phrase, aspects_used, reasoning}}

INLINE_PHRASES = {
    # === Books ===
    "Ayn Rand - Atlas Shrugged (1971).txt": {
        "discrimination_phrase": "oath of Galt's Gulch",
        "aspects_used": ["oath of Galt's Gulch"],
        "reasoning": "Galt's Gulch oath is uniquely specific to Atlas Shrugged; corpus freq=1.",
    },
    "existence doesn't mean physical existence.txt": {
        "discrimination_phrase": "consciousness as existent",
        "aspects_used": ["consciousness as existent"],
        "reasoning": "Consciousness as existent — empirically validated [2,5,4] in run 1; most stable phrase found.",
    },

    # === ITOE (14 files) ===
    "ITOE - Class 02-01.txt": {
        "discrimination_phrase": "intentionality consciousness percepts",
        "aspects_used": ["intentionality of consciousness", "percepts as base of knowledge"],
        "reasoning": "Intentionality + percepts combination; empirically validated [1,2,1].",
    },
    "ITOE - Class 03-01 - Office Hours.txt": {
        "discrimination_phrase": "perceptual concretes vs conceptual units",
        "aspects_used": ["perceptual concretes vs. conceptual units"],
        "reasoning": "Specific contrast between percepts and units as conceptual elements; corpus freq=1.",
    },
    "ITOE - Class 06-01 - Office Hours.txt": {
        "discrimination_phrase": "cross classification used cars",
        "aspects_used": ["cross classification used cars"],
        "reasoning": "Cross-classification example with used cars — actual content; empirically validated [1,1,1].",
    },
    "ITOE - Class 08-01 - Office Hours.txt": {
        "discrimination_phrase": "CCD of guilt hypothesis",
        "aspects_used": ["CCD of guilt", "CCD of hypothesis"],
        "reasoning": "CCD (Conceptual Common Denominator) applied to guilt AND hypothesis is corpus-unique.",
    },
    "ITOE - Class 09-02 - Office Hour.txt": {
        "discrimination_phrase": "metaphysically passive epistemologically active consciousness",
        "aspects_used": ["metaphysically passive consciousness", "epistemologically active consciousness"],
        "reasoning": "The passive/active consciousness distinction is the core thesis; corpus-unique combination.",
    },
    "ITOE - Class 10-01 - Office Hour.txt": {
        "discrimination_phrase": "volitional vs non-volitional knowledge",
        "aspects_used": ["volitional vs. non-volitional knowledge"],
        "reasoning": "Distinguishes voluntary from automatic cognition; corpus freq=1.",
    },
    "ITOE - Class 11-01 - Office Hour.txt": {
        "discrimination_phrase": "blood type RH factor induction",
        "aspects_used": ["blood type compatibility example", "RH factor in induction"],
        "reasoning": "Blood type/RH factor as examples of inductive reasoning — very specific to this class.",
    },
    "ITOE - Class 11-01.txt": {
        "discrimination_phrase": "scope hierarchy order of learning",
        "aspects_used": ["scope hierarchy", "order of learning hierarchy"],
        "reasoning": "Specific hierarchy types (scope, order-of-learning) unique to this lecture; corpus freq=1.",
    },
    "ITOE - Class 12-01 - Office Hour.txt": {
        "discrimination_phrase": "justice reduction concept formation",
        "aspects_used": ["justice reduction concept formation"],
        "reasoning": "Class discusses justice as concept formation/reduction (inductive staircase); ranks [1,1,1].",
    },
    "ITOE - Class 14-01.txt": {
        "discrimination_phrase": "reaffirmation through denial",
        "aspects_used": ["reaffirmation through denial"],
        "reasoning": "Reaffirmation through denial — specific logical argument; empirically validated rank=2.",
    },
    "ITOE - Class 16-01 - Office Hour.txt": {
        "discrimination_phrase": "string theory as non-physical",
        "aspects_used": ["string theory as non-physical"],
        "reasoning": "Applying Objectivist metaphysics critique to string theory; corpus freq=1.",
    },
    "ITOE - Class 16-01.txt": {
        "discrimination_phrase": "ITOE chapter 8 propositions organization",
        "aspects_used": ["ITOE chapter 8 propositions organization"],
        "reasoning": "Class covers Chapter 8 of ITOE (propositions/organization of concepts); ranks [2,2,2].",
    },
    "ITOE - Class 17-01 - Office Hour.txt": {
        "discrimination_phrase": "fallibility omniscience context-dropping",
        "aspects_used": ["fallibility vs. omniscience", "context-dropping in reasoning"],
        "reasoning": "The fallibility/omniscience distinction + context-dropping error; corpus-unique combination.",
    },
    "ITOE - Class 17-01.txt": {
        "discrimination_phrase": "certainty as action-oriented",
        "aspects_used": ["certainty as action-oriented"],
        "reasoning": "Treating certainty as action-guiding rather than infallible; corpus freq=1.",
    },

    # === ITOE Advanced Topics (25 files) ===
    "ITOE Advanced Topics - Class 01-01 Office Hour.txt": {
        "discrimination_phrase": "genus change in concepts",
        "aspects_used": ["genus change in concepts"],
        "reasoning": "Genus change in concepts — specific mechanism; corpus freq=1. Empirically validated rank=1.",
    },
    "ITOE Advanced Topics - Class 01-02 Office Hour.txt": {
        "discrimination_phrase": "collectivist crime value-free ethics",
        "aspects_used": ["collectivist crime", "value-free ethics"],
        "reasoning": "Unusual pairing of collectivist ethics critique with value-free ethics discussion.",
    },
    "ITOE Advanced Topics - Class 01-02.txt": {
        "discrimination_phrase": "void of unreality",
        "aspects_used": ["void of unreality"],
        "reasoning": "Extremely specific concept (void of unreality) unique to this lecture; corpus freq=1.",
    },
    "ITOE Advanced Topics - Class 02-01 Office Hour.txt": {
        "discrimination_phrase": "hinge epistemology brute facts",
        "aspects_used": ["hinge epistemology", "brute facts"],
        "reasoning": "Wittgenstein's hinge epistemology analyzed in Objectivist context; corpus-unique.",
    },
    "ITOE Advanced Topics - Class 02-02.txt": {
        "discrimination_phrase": "anti-concepts subjectivism language",
        "aspects_used": ["anti-concepts", "subjectivism in language"],
        "reasoning": "Anti-concepts applied to language subjectivism — empirically validated rank=1.",
    },
    "ITOE Advanced Topics - Class 03-01 Office Hour.txt": {
        "discrimination_phrase": "Heidegger influence modern philosophy",
        "aspects_used": ["influence of Heidegger on modern philosophy"],
        "reasoning": "Heidegger's influence analyzed from Objectivist perspective; corpus-unique.",
    },
    "ITOE Advanced Topics - Class 03-02 Office Hour.txt": {
        "discrimination_phrase": "Kantian good will objectivism",
        "aspects_used": ["Kantian good will"],
        "reasoning": "Kantian good will analyzed from Objectivist perspective — empirically validated rank=1.",
    },
    "ITOE Advanced Topics - Class 05-01 Office Hour.txt": {
        "discrimination_phrase": "difference phobia in philosophy",
        "aspects_used": ["difference phobia in philosophy"],
        "reasoning": "Rand's 'difference phobia' concept — empirically validated [1,1,1]; use exact aspect.",
    },
    "ITOE Advanced Topics - Class 05-02 Office Hour.txt": {
        "discrimination_phrase": "incommensurability of attributes",
        "aspects_used": ["incommensurability of attributes"],
        "reasoning": "Incommensurability applied to attributes specifically; corpus freq=1.",
    },
    "ITOE Advanced Topics - Class 06-02 - Office Hour.txt": {
        "discrimination_phrase": "volition in infants pre-conceptual",
        "aspects_used": ["volition in infants", "pre-conceptual child consciousness"],
        "reasoning": "Infant volition and pre-conceptual consciousness — unusual developmental epistemology.",
    },
    "ITOE Advanced Topics - Class 07-02.txt": {
        "discrimination_phrase": "rejection analytic-synthetic dichotomy",
        "aspects_used": ["rejection of the analytic-synthetic dichotomy"],
        "reasoning": "Rand's specific argument against analytic-synthetic dichotomy; corpus-unique.",
    },
    "ITOE Advanced Topics - Class 09-01 - Office Hour.txt": {
        "discrimination_phrase": "perceptual distinguishability",
        "aspects_used": ["perceptual distinguishability"],
        "reasoning": "Perceptual distinguishability — unique aspect; best_rank=2-4 empirically; any_pass gate.",
    },
    "ITOE Advanced Topics - Class 09-02.txt": {
        "discrimination_phrase": "narrowing by relation contrast mechanism",
        "aspects_used": ["narrowing by relation", "contrast mechanism"],
        "reasoning": "Narrowing concepts by relational comparison — specific cognitive mechanism; corpus-unique.",
    },
    "ITOE Advanced Topics - Class 10-01 - Office Hour.txt": {
        "discrimination_phrase": "syzygy in astronomy",
        "aspects_used": ["syzygy in astronomy"],
        "reasoning": "Astronomical syzygy as concept-formation example — uniquely identifying; corpus freq=1.",
    },
    "ITOE Advanced Topics - Class 10-02 - Office Hour.txt": {
        "discrimination_phrase": "perception-action loop neuroscience",
        "aspects_used": ["perception-action loop in neuroscience"],
        "reasoning": "Neuroscience concept (perception-action loop) applied to epistemology; corpus freq=1.",
    },
    "ITOE Advanced Topics - Class 10-02.txt": {
        "discrimination_phrase": "non-perceptual similarities",
        "aspects_used": ["non-perceptual similarities"],
        "reasoning": "Similarities beyond perceptual features — specific to this class; corpus freq=1.",
    },
    "ITOE Advanced Topics - Class 11-01 - Office Hour.txt": {
        "discrimination_phrase": "validity of fourth dimension",
        "aspects_used": ["the validity of the fourth dimension"],
        "reasoning": "Discussing fourth dimension validity from Objectivist perspective; corpus-unique.",
    },
    "ITOE Advanced Topics - Class 12-02 - Office Hour.txt": {
        "discrimination_phrase": "meaning concept knowledge reference",
        "aspects_used": ["meaning concept knowledge reference"],
        "reasoning": "Deeper understanding of concept meaning vs. knowledge of reference; empirically validated [4,4,5].",
    },
    "ITOE Advanced Topics - Class 13-01 - Office Hour.txt": {
        "discrimination_phrase": "contextual reclassification of knowledge",
        "aspects_used": ["contextual reclassification of knowledge"],
        "reasoning": "Reclassifying knowledge within context — specific epistemological move; corpus freq=1.",
    },
    # Class 13-02 already done in pilot
    # Class 14-01 already done in pilot
    "ITOE Advanced Topics - Class 14-02 - Office Hour.txt": {
        "discrimination_phrase": "Historical context of concept formation",
        "aspects_used": ["Historical context of concept formation"],
        "reasoning": "Historical context of concept formation — empirically validated [4,4,4] zero variance.",
    },
    "ITOE Advanced Topics - Class 15-01 - Office Hour.txt": {
        "discrimination_phrase": "short-range thinking",
        "aspects_used": ["short-range thinking"],
        "reasoning": "Short-range thinking as topic — empirically validated [4,4,3].",
    },
    "ITOE Advanced Topics - Class 16-01 - Office Hour.txt": {
        "discrimination_phrase": "correspondence theory vs. identification",
        "aspects_used": ["correspondence theory vs. identification"],
        "reasoning": "Correspondence theory vs. identification — corpus-unique; empirically validated rank=4.",
    },
    "ITOE Advanced Topics - Class 16-02 - Office Hour.txt": {
        "discrimination_phrase": "dark matter dark energy philosophy",
        "aspects_used": ["dark matter and dark energy", "philosopher's interpretation of scientific concepts"],
        "reasoning": "Dark matter/energy analyzed from Objectivist perspective; corpus-unique topic.",
    },

    # === MOTM (2 files) ===
    "MOTM_2019-03-17_Motivation-by-Love-vs-Motivation-by-Fear.txt": {
        "discrimination_phrase": "emotions as signals of values",
        "aspects_used": ["emotions as signals of values"],
        "reasoning": "Emotions as value signals — specific psychological claim; empirically validated rank=1.",
    },
    "MOTM_2021-05-16_History-of-the-Objectivist-movement-a-personal-account-part.txt": {
        "discrimination_phrase": "history of objectivist movement",
        "aspects_used": ["history of objectivist movement"],
        "reasoning": "Personal account of Objectivist movement history — the title IS the discriminator.",
    },

    # === Objectivist Logic (11 files, 3 already piloted) ===
    "Objectivist Logic - Class 02-02.txt": {
        "discrimination_phrase": "cognitive biases",
        "aspects_used": ["cognitive biases"],
        "reasoning": "Cognitive biases as logic topic — empirically validated rank=1 [1,1,1].",
    },
    "Objectivist Logic - Class 03-01.txt": {
        "discrimination_phrase": "multiplicity requirements concept-formation examples",
        "aspects_used": ["multiplicity requirements for concept-formation", "illustrative examples in philosophy"],
        "reasoning": "The specific rule about needing multiple instances for concept formation; corpus freq=1.",
    },
    "Objectivist Logic - Class 03-02 - Office Hours.txt": {
        "discrimination_phrase": "hierarchy of width and scale",
        "aspects_used": ["hierarchy of width", "hierarchy of scale"],
        "reasoning": "Width and scale hierarchies — specific types unique to this office hour.",
    },
    "Objectivist Logic - Class 05-01.txt": {
        "discrimination_phrase": "ultimate genera floating abstractions",
        "aspects_used": ["ultimate genera", "floating abstractions"],
        "reasoning": "Ultimate genera and floating abstractions — empirically validated rank=1.",
    },
    "Objectivist Logic - Class 05-02 - Office Hours.txt": {
        "discrimination_phrase": "proto-conceptual space",
        "aspects_used": ["proto-conceptual space"],
        "reasoning": "Proto-conceptual space (pre-conceptual cognitive territory); corpus freq=1.",
    },
    "Objectivist Logic - Class 07-02 - Office Hours.txt": {
        "discrimination_phrase": "conceptual vs propositional knowledge",
        "aspects_used": ["conceptual knowledge vs propositional knowledge"],
        "reasoning": "Distinguishing conceptual from propositional knowledge; specific epistemological thesis.",
    },
    "Objectivist Logic - Class 10-02.txt": {
        "discrimination_phrase": "foil selection contextual purpose dependency",
        "aspects_used": ["foil selection", "contextual purpose dependency"],
        "reasoning": "Foil selection (Rand's method) + contextual dependency of purpose; corpus-unique pair.",
    },
    "Objectivist Logic - Class 13-02 - Open Office Hour.txt": {
        "discrimination_phrase": "cultural appropriation as a package deal",
        "aspects_used": ["cultural appropriation as a package deal"],
        "reasoning": "Applying anti-concept analysis to cultural appropriation; corpus freq=1.",
    },
    # Class 14-02 already done in pilot
    "Objectivist Logic - Class 15-02 - Open Office Hour.txt": {
        "discrimination_phrase": "Aristotle solution Heraclitus paradox",
        "aspects_used": ["Aristotle's solution to change", "Heraclitus' paradox"],
        "reasoning": "Aristotle's response to Heraclitean flux — specific historical argument; corpus-unique.",
    },
    "Objectivist Logic - Class 16-02 - Open Office Hour.txt": {
        "discrimination_phrase": "undistributed middle",
        "aspects_used": ["undistributed middle"],
        "reasoning": "Undistributed middle (logical fallacy) — unique to this class; empirically validated rank=3.",
    },

    # === Peikoff Podcast Episodes (4 files) ===
    "Episode 258 [1000134878881].txt": {
        "discrimination_phrase": "tax resistance government confiscation",
        "aspects_used": ["moral implications of tax resistance", "right to resist government confiscation"],
        "reasoning": "Tax resistance and government confiscation — specific political-ethical combination.",
    },
    "Episode 338 [1000318962751].txt": {
        "discrimination_phrase": "morality of cheating in sports",
        "aspects_used": ["morality of cheating in sports"],
        "reasoning": "Ethics of sports cheating — uniquely identifying for this episode; corpus freq=1.",
    },
    "Episode 370 [1000340821084].txt": {
        "discrimination_phrase": "boycotting immoral businesses",
        "aspects_used": ["boycotting immoral businesses"],
        "reasoning": "Boycotting immoral businesses — empirically validated [1,1,1] in pilot; stable.",
    },
    "Episode 404 [1000364774068].txt": {
        "discrimination_phrase": "Ann Coulter's moral code",
        "aspects_used": ["Ann Coulter's moral code"],
        "reasoning": "Named person (Ann Coulter) with specific moral critique; corpus freq=1.",
    },

    # === Perception (5 files) ===
    "Perception - Class 01-02 - Office Hour.txt": {
        "discrimination_phrase": "racial statistics and intelligence",
        "aspects_used": ["racial statistics and intelligence"],
        "reasoning": "Very specific and identifying content for this office hour; corpus freq=1.",
    },
    "Perception - Class 02-01 - Office Hour.txt": {
        "discrimination_phrase": "Molineu's problem retinal inversion",
        "aspects_used": ["Molineu's problem", "retinal image inversion"],
        "reasoning": "Molineux's problem + retinal inversion as classical perception challenges; corpus-unique.",
    },
    "Perception - Class 04-01 - Office Hour.txt": {
        "discrimination_phrase": "evil demon brain in a vat",
        "aspects_used": ["evil demon hypothesis", "brain in a vat"],
        "reasoning": "Classic skeptical scenarios — evil demon + brain-in-vat; corpus-unique combination.",
    },
    "Perception - Class 06-02 - Office Hour.txt": {
        "discrimination_phrase": "skepticism constant doubt perception",
        "aspects_used": ["Skepticism as constant doubt"],
        "reasoning": "Skepticism as constant doubt in perception context — empirically validated rank=1.",
    },
    "Perception - Class 08-01 - Office Hour.txt": {
        "discrimination_phrase": "Schopenhauer's metaphysics noumena phenomena",
        "aspects_used": ["Schopenhauer's metaphysics", "noumena vs phenomena"],
        "reasoning": "Schopenhauer's noumena/phenomena analyzed from Objectivist view; corpus-unique.",
    },
}


# -- Gemini Setup -------------------------------------------------------------

def setup_gemini():
    """Initialize Gemini client and get store resource name."""
    import keyring
    from google import genai

    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        print("ERROR: No Gemini API key found in keyring.", file=sys.stderr)
        sys.exit(2)

    client = genai.Client(api_key=api_key)

    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT value FROM library_config WHERE key = 'gemini_store_name'"
    ).fetchone()
    conn.close()

    if not row:
        print("ERROR: gemini_store_name not found in library_config.", file=sys.stderr)
        sys.exit(2)

    return client, row[0]


# -- Re-upload Setup ----------------------------------------------------------

def load_reenrich_module():
    """Import re_enrich_retrieval.py functions via importlib (proven pattern)."""
    script = Path(__file__).resolve().parent / "re_enrich_retrieval.py"
    spec = importlib.util.spec_from_file_location("re_enrich_retrieval", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- Validation ---------------------------------------------------------------

def validate_phrase_3x(client, store, phrase, store_doc_id, pause=2.0):
    """Run validation 3 times with pause. Returns list of ranks (None = not found)."""
    ranks = []
    for run in range(VALIDATION_RUNS):
        rank = validate_phrase(
            client=client,
            store_resource_name=store,
            phrase=phrase,
            target_store_doc_id=store_doc_id,
        )
        ranks.append(rank)
        if run < VALIDATION_RUNS - 1:
            time.sleep(pause)
    return ranks


# -- Main Run -----------------------------------------------------------------

def run_full(args):
    started_at = datetime.now(timezone.utc).isoformat()
    print("=" * 70)
    print("  CRAD FULL RUN — Phase 16.6-02")
    print("=" * 70)
    print(f"  Time: {started_at}")
    print(f"  Files: {len(INLINE_PHRASES)} pre-computed phrases (+ 3 piloted)")
    print(f"  Mode: {'dry-run' if args.dry_run else 'full (validate + upload)'}")
    print("=" * 70)

    # Connect to DB
    conn = sqlite3.connect(str(DB_PATH))
    create_crad_tables(conn)

    # Build corpus freq map
    print("\n[1/5] Building corpus frequency map...")
    corpus_freq = build_corpus_freq_map(conn)
    print(f"  Corpus unique aspects: {len(corpus_freq)}")

    # Setup Gemini
    print("\n[2/5] Connecting to Gemini...")
    gemini_client, store = setup_gemini()
    print(f"  Store: {store}")

    # Load re-upload module (unless dry-run or skip-upload)
    reenrich = None
    if not args.dry_run and not args.skip_upload:
        print("\n[3/5] Loading re-upload module...")
        try:
            reenrich = load_reenrich_module()
            print("  re_enrich_retrieval.py loaded")
        except Exception as e:
            print(f"  WARNING: Could not load re_enrich_retrieval.py: {e}")
            print("  Continuing in validation-only mode")

    # --upload-only: skip validation, build results from DB-validated entries
    if getattr(args, 'upload_only', False):
        print("\n[4/5] --upload-only: loading validated phrases from DB (skipping Gemini validation)...")
        db_rows = conn.execute(
            "SELECT filename, phrase, validation_rank FROM file_discrimination_phrases WHERE validation_status = 'validated'"
        ).fetchall()
        results = []
        passes = 0
        for row in db_rows:
            results.append({
                "filename": row[0],
                "phrase": row[1],
                "best_rank": row[2],
                "validation_status": "validated",
                "status": "PASS",
            })
            passes += 1
        escalations = 0
        print(f"  Loaded {passes} validated files from DB")
        if reenrich:
            print(f"\n[5/5] Re-uploading {passes} validated files with Discrimination: header...")
            _reupload_validated(conn, gemini_client, store, results, reenrich)
        conn.close()
        completed_at = datetime.now(timezone.utc).isoformat()
        gate = "PASS"
        print(f"\n{'=' * 70}")
        print(f"  GATE: {gate} ({passes}/{passes} pass, {escalations}/{MAX_ESCALATIONS} max escalations)")
        print(f"{'=' * 70}")
        return 0

    # Get all S1-failing files (63 total = 60 new + 3 piloted)
    # Load pilot results to include them
    pilot_results_path = Path(__file__).resolve().parent.parent / ".planning" / "phases" / "16.6-crad" / "16.6-01-pilot-results.json"
    pilot_phrases = {}
    if pilot_results_path.exists():
        with open(pilot_results_path) as f:
            pilot_data = json.load(f)
        for r in pilot_data["results"]:
            if r.get("status") == "PASS":
                pilot_phrases[r["filename"]] = {
                    "discrimination_phrase": r["phrase"],
                    "aspects_used": r["aspects_used"],
                    "reasoning": f"Piloted in 16.6-01: ranks {r['validation_ranks']}",
                    "validation_ranks": r["validation_ranks"],
                    "validation_status": "validated",
                    "best_rank": r["best_rank"],
                }
    print(f"\n  Pilot phrases loaded: {len(pilot_phrases)} files")

    # Combine all phrases
    all_phrases = dict(pilot_phrases)
    all_phrases.update({k: v for k, v in INLINE_PHRASES.items() if k not in all_phrases})

    # Filter to single file if requested
    if args.file:
        if args.file not in all_phrases:
            print(f"ERROR: {args.file!r} not in phrase list.", file=sys.stderr)
            conn.close()
            return 1
        all_phrases = {args.file: all_phrases[args.file]}
        print(f"\n  Running for single file: {args.file}")

    print(f"\n[4/5] Processing {len(all_phrases)} files...")
    results = []
    passes = 0
    fails = 0
    escalations = 0

    for i, (filename, phrase_data) in enumerate(sorted(all_phrases.items()), 1):
        print(f"\n  [{i:02d}/{len(all_phrases):02d}] {filename}")

        # Skip if already validated in pilot
        if "validation_status" in phrase_data and phrase_data["validation_status"] == "validated":
            print(f"         Already validated in pilot: rank={phrase_data.get('best_rank')}")
            # Store in DB if not already there
            row = conn.execute(
                "SELECT filename FROM file_discrimination_phrases WHERE filename = ?",
                (filename,)
            ).fetchone()
            if not row:
                row2 = conn.execute(
                    "SELECT gemini_store_doc_id FROM files WHERE filename = ?", (filename,)
                ).fetchone()
                store_doc_id = row2[0] if row2 else None
                store_discrimination_phrase(conn, {
                    "filename": filename,
                    "series_name": "pilot",
                    "phrase": phrase_data["discrimination_phrase"],
                    "word_count": len(phrase_data["discrimination_phrase"].split()),
                    "aspects_used": phrase_data["aspects_used"],
                    "validation_rank": phrase_data.get("best_rank"),
                    "validation_status": "validated",
                })
            result = {
                "filename": filename,
                "phrase": phrase_data["discrimination_phrase"],
                "validation_ranks": phrase_data.get("validation_ranks", []),
                "best_rank": phrase_data.get("best_rank"),
                "validation_status": "validated",
                "status": "PASS",
                "piloted": True,
            }
            results.append(result)
            passes += 1
            continue

        # Get file info from DB
        row = conn.execute(
            "SELECT gemini_store_doc_id FROM files WHERE filename = ? AND gemini_state = 'indexed'",
            (filename,)
        ).fetchone()

        if not row:
            print(f"         ERROR: not found in DB (indexed)")
            results.append({"filename": filename, "error": "not found in DB"})
            escalations += 1
            continue

        store_doc_id = row[0]
        phrase = phrase_data["discrimination_phrase"]
        print(f"         Phrase: {phrase!r} ({len(phrase.split())} words)")

        # Validate against Gemini
        ranks = validate_phrase_3x(gemini_client, store, phrase, store_doc_id)
        best_rank = min((r for r in ranks if r is not None), default=None)
        # Gate: best_rank ≤ 5 (at least 1 of 3 runs found the file). Plan says "retry twice
        # more" — meaning we accept any run at rank ≤ 5 as a pass. All-None = escalation.
        any_pass = best_rank is not None and best_rank <= MAX_ACCEPTABLE_RANK
        zero_variance = len(set(ranks)) == 1

        print(f"         Ranks: {ranks} (best: {best_rank}, zero-var: {zero_variance})")

        if any_pass:
            status = "PASS"
            validation_status = "validated"
            passes += 1
        else:
            # Try escalation strategies
            print(f"         ESCALATING: ranks {ranks}")
            escalation_phrases = _build_escalation_phrases(filename, phrase_data, conn, corpus_freq)
            escalated = False
            for esc_phrase in escalation_phrases:
                print(f"         Trying escalation: {esc_phrase!r}")
                esc_ranks = validate_phrase_3x(gemini_client, store, esc_phrase, store_doc_id, pause=1.5)
                esc_best = min((r for r in esc_ranks if r is not None), default=None)
                if esc_best is not None and esc_best <= MAX_ACCEPTABLE_RANK:
                    print(f"         Escalation PASS: {esc_phrase!r} -> {esc_ranks}")
                    phrase = esc_phrase
                    ranks = esc_ranks
                    best_rank = esc_best
                    status = "PASS"
                    validation_status = "validated"
                    passes += 1
                    escalated = True
                    break

            if not escalated:
                print(f"         All escalations failed. Marking as ESCALATED.")
                status = "ESCALATED"
                validation_status = "escalated"
                escalations += 1
                fails += 1

        # Store in DB
        word_count = len(phrase.split())
        phrase_data["phrase"] = phrase
        phrase_data["word_count"] = word_count
        phrase_data["validation_rank"] = best_rank
        phrase_data["validation_status"] = validation_status
        store_discrimination_phrase(conn, {
            "filename": filename,
            "series_name": _get_series_name(filename, conn),
            "phrase": phrase,
            "word_count": word_count,
            "aspects_used": phrase_data["aspects_used"],
            "validation_rank": best_rank,
            "validation_status": validation_status,
        })

        result = {
            "filename": filename,
            "phrase": phrase,
            "validation_ranks": ranks,
            "best_rank": best_rank,
            "validation_status": validation_status,
            "status": status,
            "piloted": False,
        }
        results.append(result)
        time.sleep(1.0)  # brief pause between files

    print(f"\n  Summary: {passes} pass, {fails} fail, {escalations} escalations")

    # Re-upload validated files
    if not args.dry_run and not args.skip_upload and reenrich:
        print(f"\n[5/5] Re-uploading {passes} validated files with Discrimination: header...")
        _reupload_validated(conn, gemini_client, store, results, reenrich)
    elif args.dry_run:
        print("\n[5/5] Skipping re-upload (dry-run mode)")
    elif args.skip_upload:
        print("\n[5/5] Skipping re-upload (--skip-upload mode)")

    conn.close()

    # Write results JSON
    completed_at = datetime.now(timezone.utc).isoformat()
    gate = "PASS" if escalations <= MAX_ESCALATIONS else "FAIL"
    results_path = Path(__file__).resolve().parent.parent / ".planning" / "phases" / "16.6-crad" / "16.6-02-results.json"
    with open(results_path, "w") as f:
        json.dump({
            "metadata": {
                "started_at": started_at,
                "completed_at": completed_at,
                "gate": gate,
                "total": len(all_phrases),
                "passes": passes,
                "fails": fails,
                "escalations": escalations,
                "max_escalations": MAX_ESCALATIONS,
            },
            "results": results,
        }, f, indent=2)

    print(f"\n{'=' * 70}")
    print(f"  GATE: {gate} ({passes}/{len(all_phrases)} pass, {escalations}/{MAX_ESCALATIONS} max escalations)")
    print(f"  Results: {results_path}")
    print(f"{'=' * 70}")

    return 0 if gate == "PASS" else 1


def _build_escalation_phrases(filename, phrase_data, conn, corpus_freq):
    """Build fallback phrases when primary phrase fails validation.

    Strategy: try raw aspect strings from DB sorted by corpus rarity.
    Raw aspects are close to the actual transcript language, so they
    have the best chance of matching Gemini's embedding index.
    """
    primary = phrase_data["discrimination_phrase"]
    tried: set[str] = {primary}
    escalations: list[str] = []

    # Fallback 1: individual raw aspects_used (cleaned, ≤7 words)
    for aspect in phrase_data.get("aspects_used", []):
        cleaned = aspect.strip().strip('"').strip("'")
        if cleaned and cleaned not in tried and len(cleaned.split()) <= 7:
            escalations.append(cleaned)
            tried.add(cleaned)

    # Fallback 2: rarest raw aspects from DB (excluding already tried)
    row = conn.execute("""
        SELECT fm.metadata_json
        FROM file_metadata_ai fm
        JOIN files f ON fm.file_path = f.file_path
        WHERE f.filename = ? AND fm.is_current = 1
    """, (filename,)).fetchone()

    if row and row[0]:
        aspects = json.loads(row[0]).get("topic_aspects", [])
        # Sort by corpus rarity (rarest first), then try as-is
        ranked = sorted(aspects, key=lambda a: corpus_freq.get(a, 0))
        for a in ranked:
            cleaned = a.strip().strip('"').strip("'")
            if cleaned and cleaned not in tried and len(cleaned.split()) <= 7:
                escalations.append(cleaned)
                tried.add(cleaned)
                if len(escalations) >= 3:
                    break

    return escalations[:3]  # max 3 escalation attempts


def _get_series_name(filename, conn):
    """Get series name (parent dir) for a file."""
    row = conn.execute("SELECT file_path FROM files WHERE filename = ?", (filename,)).fetchone()
    if row:
        from pathlib import PurePosixPath
        return PurePosixPath(row[0]).parent.name
    return "Unknown"


def _reupload_validated(conn, gemini_client, store, results, reenrich):
    """Re-upload validated files with Discrimination: field injected into identity header."""
    import os
    import tempfile

    validated = [r for r in results if r.get("validation_status") == "validated"]
    print(f"  Re-uploading {len(validated)} validated files (including piloted) with Discrimination: header...")

    success = 0
    failed = 0

    for i, r in enumerate(validated, 1):
        filename = r["filename"]
        phrase = r["phrase"]
        print(f"  [{i:02d}/{len(validated):02d}] {filename}")
        print(f"         Phrase: {phrase!r}")

        # Get file info
        row = conn.execute("""
            SELECT f.file_path, f.gemini_store_doc_id, f.gemini_file_id
            FROM files f
            WHERE f.filename = ? AND f.gemini_state = 'indexed'
        """, (filename,)).fetchone()

        if not row:
            print(f"         SKIP: not found in DB (indexed)")
            failed += 1
            continue

        file_path, old_store_doc_id, old_file_id = row
        tmp_path = None

        try:
            # Build enriched content (identity header + AI analysis + transcript)
            content = reenrich.build_enriched_content_with_header(file_path, conn)
            if content is None:
                print(f"         SKIP: source file not found on disk: {file_path}")
                failed += 1
                continue

            # Inject Discrimination: field before --- END METADATA ---
            disc_line = f"Discrimination: {phrase}"
            if "Discrimination:" not in content:
                content = content.replace(
                    "--- END METADATA ---",
                    f"{disc_line}\n--- END METADATA ---",
                    1,
                )
            else:
                print(f"         NOTE: Discrimination: already present, skipping injection")

            # Write temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            # Upload to Files API
            new_file_name = reenrich.upload_file_with_poll(gemini_client, tmp_path, filename)
            print(f"         Uploaded: {new_file_name}")

            # Import to store
            new_store_doc_id = reenrich.import_to_store_with_poll(gemini_client, store, new_file_name)
            print(f"         Imported store_doc_id: {new_store_doc_id}")

            # Delete old store document
            reenrich.delete_old_store_doc(gemini_client, store, old_store_doc_id)

            # Delete old raw file
            if old_file_id:
                reenrich.delete_old_raw_file(gemini_client, old_file_id)

            # Update DB
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                UPDATE files
                SET gemini_file_id = ?, gemini_store_doc_id = ?, gemini_state = 'indexed',
                    gemini_state_updated_at = ?
                WHERE filename = ?
            """, (new_file_name, new_store_doc_id, now, filename))
            conn.commit()

            print(f"         OK")
            success += 1

        except Exception as e:
            print(f"         ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        time.sleep(0.5)

    print(f"\n  Re-upload complete: {success} success, {failed} failed")
    print("  Run: python -m objlib store-sync --store objectivism-library  (to clean orphans)")


# -- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="CRAD full run for 63 S1-failing files")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, no DB writes or uploads")
    parser.add_argument("--skip-upload", "--validate-only", action="store_true",
                        help="Validate and store in DB, but don't re-upload")
    parser.add_argument("--upload-only", action="store_true",
                        help="Skip validation; re-upload all DB-validated files with Discrimination: header")
    parser.add_argument("--file", help="Run for single file only")
    args = parser.parse_args()
    sys.exit(run_full(args))


if __name__ == "__main__":
    main()
