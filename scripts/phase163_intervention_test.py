#!/usr/bin/env python3
"""Phase 16.3 intervention test: prove identity header fix works on failing files.

Safety: ONLY touches objectivism-library-retrieval-test store.
Never touches objectivism-library (production).
Deletes test store after validation.

Test design:
  - Category A (class-number files): 3 WITH header, 2 WITHOUT header (control)
  - Category B (MOTM files): 3 WITH header, 2 WITHOUT header (control)
  - Working files: 3 WITH header (regression check)
  Total: 13 files in ephemeral store

Expected results:
  - E-A (Cat A WITH header): >80% hit rate (proves fix works)
  - C-A (Cat A WITHOUT header): low hit rate (confirms baseline failure)
  - E-B (Cat B WITH header): improved over control
  - C-B (Cat B WITHOUT header): low hit rate (confirms baseline failure)
  - W-H (Working WITH header): >95% hit rate (no regression)
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

import keyring
from google import genai
from google.genai import types as genai_types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from objlib.upload.header_builder import build_identity_header

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "library.db")
TEST_STORE_DISPLAY_NAME = "objectivism-library-retrieval-test"
PRODUCTION_STORE_DISPLAY_NAME = "objectivism-library"
SEARCH_MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Test file definitions
# ---------------------------------------------------------------------------

# Category A experimental: class-number files WITH identity header
CAT_A_WITH_HEADER = [
    "Objectivist Logic - Class 09-02.txt",
    "ITOE Advanced Topics - Class 02-02.txt",
    "Objectivist Logic - Class 02-02 - Office Hours.txt",
]

# Category A control: class-number files WITHOUT identity header
CAT_A_WITHOUT_HEADER = [
    "ITOE Advanced Topics - Class 05-02 Office Hour.txt",
    "ITOE Advanced Topics - Class 13-02 - Office Hour.txt",
]

# Category B experimental: MOTM files WITH identity header
CAT_B_WITH_HEADER = [
    "MOTM_2019-03-03_Passages-from-and-positions-of-Ayn-Rand.txt",
    "MOTM_2021-06-13_History-of-the-Objectivist-movement-a-personal-account-part.txt",
    "MOTM_2022-08-21_Thinking-In-Examples.txt",
]

# Category B control: MOTM files WITHOUT identity header (randomly selected)
CAT_B_WITHOUT_HEADER = [
    "MOTM_2021-03-07_Interview-of-Mike-Garrett.txt",
    "MOTM_2018-11-25_Psycho-teleology-applications.txt",
]

# Working files: regression check WITH identity header
WORKING_WITH_HEADER = [
    "Leonard Peikoff at the Ford Hall Forum - Lesson 12 - A Philosopher Looks at the O. J. Verdict.txt",
    "Leonard Peikoff at the Ford Hall Forum - Lesson 03 - The American School_ Why Johnny Can_t Think.txt",
    "Leonard Peikoff at the Ford Hall Forum - Lesson 09 - Some Notes About Tomorrow.txt",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_file_path(conn: sqlite3.Connection, filename: str) -> str | None:
    """Look up file_path from filename."""
    row = conn.execute(
        "SELECT file_path FROM files WHERE filename = ?", (filename,)
    ).fetchone()
    return row[0] if row else None


def build_query(filename: str, conn: sqlite3.Connection) -> str:
    """Build a targeted search query from file metadata.

    Mirrors the A7 query strategy from check_stability.py.
    """
    file_path = get_file_path(conn, filename)
    stem = PurePosixPath(filename).stem

    # Try to use metadata topic (same as check_stability.py A7)
    if file_path:
        row = conn.execute(
            "SELECT metadata_json FROM files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        if row and row[0]:
            try:
                meta = json.loads(row[0])
                title = (
                    meta.get("display_title")
                    or meta.get("title")
                    or meta.get("topic")
                )
                if title:
                    return f"What is '{title}' about?"
            except (json.JSONDecodeError, TypeError):
                pass

    return f"What is '{stem}' about?"


async def wait_for_file_active(
    client: genai.Client, file_name: str, timeout: float = 120.0
) -> object:
    """Poll until uploaded file reaches ACTIVE state."""
    start = time.perf_counter()
    interval = 1.0

    while True:
        elapsed = time.perf_counter() - start
        if elapsed >= timeout:
            raise TimeoutError(f"File {file_name} not ACTIVE after {timeout}s")

        file_obj = await client.aio.files.get(name=file_name)
        state_name = getattr(file_obj.state, "name", str(file_obj.state)) if hasattr(file_obj, "state") else "UNKNOWN"

        if state_name == "ACTIVE":
            return file_obj
        if state_name == "FAILED":
            raise RuntimeError(f"File processing failed: {file_name}")

        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 10.0)


async def wait_for_import_done(
    client: genai.Client, operation: object, timeout: float = 180.0
) -> dict:
    """Poll import operation until done using raw API client."""
    start = time.perf_counter()
    interval = 1.0
    op_name = operation.name

    # Check if already done
    if getattr(operation, "done", None):
        if getattr(operation, "error", None):
            raise RuntimeError(f"Import operation failed: {operation.error}")
        resp = getattr(operation, "response", None)
        doc_name = getattr(resp, "document_name", None) if resp else None
        return {"done": True, "document_name": doc_name, "operation_name": op_name}

    while True:
        elapsed = time.perf_counter() - start
        if elapsed >= timeout:
            raise TimeoutError(f"Import operation {op_name} not done after {timeout}s")

        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 10.0)

        try:
            response = await client.aio._api_client.async_request(
                "get", op_name, {}, None
            )
            response_dict = {} if not response.body else json.loads(response.body)
        except Exception as e:
            print(f"    Warning: poll error for {op_name}: {e}")
            continue

        if response_dict.get("done"):
            if response_dict.get("error"):
                raise RuntimeError(
                    f"Import operation failed: {response_dict['error']}"
                )
            resp = response_dict.get("response", {})
            document_name = resp.get("documentName")
            return {
                "done": True,
                "document_name": document_name,
                "operation_name": op_name,
            }


async def upload_and_import_file(
    client: genai.Client,
    store_name: str,
    filename: str,
    content: str,
) -> dict:
    """Upload content to Files API and import to store.

    Returns dict with file_name, document_name, store_doc_id, store_doc_prefix.
    """
    # Write content to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Upload to Files API
        file_obj = await client.aio.files.upload(
            file=tmp_path,
            config={"display_name": filename[:512]},
        )
        print(f"    Uploaded: {file_obj.name}")

        # Wait for ACTIVE
        file_obj = await wait_for_file_active(client, file_obj.name)
        print(f"    Active: {file_obj.name}")

        # Import to store
        import_op = await client.aio.file_search_stores.import_file(
            file_search_store_name=store_name,
            file_name=file_obj.name,
        )
        print(f"    Import started: {import_op.name}")

        # Wait for import done
        result = await wait_for_import_done(client, import_op)

        document_name = result.get("document_name")
        if document_name and "/" not in document_name:
            document_name = f"{store_name}/documents/{document_name}"

        # Extract store doc ID and prefix for matching
        store_doc_id = document_name.split("/")[-1] if document_name else ""
        store_doc_prefix = store_doc_id.split("-")[0] if store_doc_id else ""

        print(f"    Imported: doc={document_name}")
        print(f"    Store doc prefix: {store_doc_prefix}")

        return {
            "file_name": file_obj.name,
            "document_name": document_name,
            "store_doc_id": store_doc_id,
            "store_doc_prefix": store_doc_prefix,
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def search_for_file(
    client: genai.Client,
    store_name: str,
    query: str,
    target_prefix: str,
    top_k: int = 10,
) -> tuple[bool, int | None]:
    """Run a search query and check if target file is in top-K results.

    Returns (found, rank) where rank is 1-indexed or None if not found.
    """
    try:
        response = await client.aio.models.generate_content(
            model=SEARCH_MODEL,
            contents=query,
            config=genai_types.GenerateContentConfig(
                tools=[genai_types.Tool(
                    file_search=genai_types.FileSearch(
                        file_search_store_names=[store_name]
                    )
                )]
            ),
        )
    except Exception as e:
        print(f"    Search error: {e}")
        return False, None

    if not response.candidates:
        return False, None

    gm = getattr(response.candidates[0], "grounding_metadata", None)
    if not gm:
        return False, None

    chunks = getattr(gm, "grounding_chunks", []) or []

    seen_titles = []
    for i, chunk in enumerate(chunks[:top_k]):
        rc = getattr(chunk, "retrieved_context", None)
        if not rc:
            continue
        title = getattr(rc, "title", "") or ""
        seen_titles.append(title)
        if title and title == target_prefix:
            return True, i + 1

    # Debug: show what titles were returned
    if seen_titles:
        unique_titles = list(dict.fromkeys(seen_titles))
        print(f"    Seen titles (not matching {target_prefix}): {unique_titles[:5]}")

    return False, None


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

async def run_intervention_test():
    """Execute the full intervention test."""
    start_time = time.time()

    # Get API key
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        print("ERROR: No API key found in keyring. Run: keyring set objlib-gemini api_key")
        sys.exit(2)

    client = genai.Client(api_key=api_key)
    conn = sqlite3.connect(DB_PATH)

    # Record production store doc count BEFORE test
    print("=" * 70)
    print("  Phase 16.3 Intervention Test")
    print("=" * 70)
    print()

    # Get production store resource name
    prod_store_name = "fileSearchStores/objectivismlibrary-9xl9top0qu6u"
    try:
        prod_store = await client.aio.file_search_stores.get(name=prod_store_name)
        prod_doc_count_before = getattr(prod_store, "active_documents_count", "UNKNOWN")
        print(f"Production store doc count BEFORE: {prod_doc_count_before}")
    except Exception as e:
        prod_doc_count_before = "ERROR"
        print(f"Warning: could not read production store: {e}")

    # Step 1: Create ephemeral test store
    print(f"\nCreating test store: {TEST_STORE_DISPLAY_NAME}")
    test_store = await client.aio.file_search_stores.create(
        config={"display_name": TEST_STORE_DISPLAY_NAME}
    )
    test_store_name = test_store.name
    print(f"  Store created: {test_store_name}")

    results = []
    uploaded_file_names = []  # Track for cleanup

    try:
        # Step 2: Upload all test files
        all_files = [
            # (filename, condition, category, with_header)
            *[(f, "E-A", "Cat A", True) for f in CAT_A_WITH_HEADER],
            *[(f, "C-A", "Cat A", False) for f in CAT_A_WITHOUT_HEADER],
            *[(f, "E-B", "Cat B", True) for f in CAT_B_WITH_HEADER],
            *[(f, "C-B", "Cat B", False) for f in CAT_B_WITHOUT_HEADER],
            *[(f, "W-H", "Working", True) for f in WORKING_WITH_HEADER],
        ]

        file_records = {}  # filename -> upload result dict

        for filename, condition, category, with_header in all_files:
            print(f"\n--- {condition} ({category}): {filename} ---")

            file_path = get_file_path(conn, filename)
            if not file_path:
                print(f"  ERROR: File not found in DB: {filename}")
                results.append({
                    "filename": filename,
                    "condition": condition,
                    "category": category,
                    "error": "File not found in DB",
                })
                continue

            # Read raw transcript
            try:
                transcript = Path(file_path).read_text(encoding="utf-8")
            except Exception as e:
                print(f"  ERROR: Cannot read file: {e}")
                results.append({
                    "filename": filename,
                    "condition": condition,
                    "category": category,
                    "error": f"Cannot read file: {e}",
                })
                continue

            # Build content
            if with_header:
                identity_header = build_identity_header(file_path, conn)
                content = identity_header + "\n" + transcript
                print(f"  Header: {len(identity_header)} bytes")
            else:
                content = transcript
                print(f"  No header (control)")

            # Upload and import
            try:
                record = await upload_and_import_file(
                    client, test_store_name, filename, content
                )
                file_records[filename] = record
                uploaded_file_names.append(record["file_name"])
            except Exception as e:
                print(f"  ERROR: Upload/import failed: {e}")
                results.append({
                    "filename": filename,
                    "condition": condition,
                    "category": category,
                    "error": f"Upload/import failed: {e}",
                })
                continue

        # Step 3: Wait for search index to settle
        print(f"\n{'='*70}")
        successful_uploads = len(file_records)
        print(f"Uploaded {successful_uploads}/{len(all_files)} files successfully")

        if successful_uploads == 0:
            print("ERROR: No files uploaded successfully. Aborting test.")
            return results, prod_doc_count_before, "ERROR"

        settle_time = 30
        print(f"Waiting {settle_time}s for search index to settle...")
        await asyncio.sleep(settle_time)

        # Step 4: Run targeted queries
        print(f"\n{'='*70}")
        print("  Running targeted queries")
        print(f"{'='*70}")

        for filename, condition, category, with_header in all_files:
            if filename not in file_records:
                continue  # Skip failed uploads

            record = file_records[filename]
            query = build_query(filename, conn)
            target_prefix = record["store_doc_prefix"]

            print(f"\n  {condition}: {filename}")
            print(f"  Query: {query}")
            print(f"  Target prefix: {target_prefix}")

            found, rank = await search_for_file(
                client, test_store_name, query, target_prefix
            )

            result = {
                "filename": filename,
                "condition": condition,
                "category": category,
                "query": query,
                "found": found,
                "rank": rank,
                "store_doc_prefix": target_prefix,
            }
            results.append(result)

            status = f"FOUND at rank {rank}" if found else "NOT FOUND"
            print(f"  Result: {status}")

            # Rate limit: avoid hammering the API
            await asyncio.sleep(2)

        # Step 5: Check production store is untouched
        prod_doc_count_after = "UNKNOWN"
        try:
            prod_store_after = await client.aio.file_search_stores.get(name=prod_store_name)
            prod_doc_count_after = getattr(prod_store_after, "active_documents_count", "UNKNOWN")
            print(f"\nProduction store doc count AFTER: {prod_doc_count_after}")
        except Exception as e:
            prod_doc_count_after = "ERROR"
            print(f"Warning: could not read production store: {e}")

    finally:
        # Step 6: Cleanup - delete test store
        print(f"\n{'='*70}")
        print("  Cleanup")
        print(f"{'='*70}")

        try:
            # Delete raw files first
            for file_name in uploaded_file_names:
                try:
                    await client.aio.files.delete(name=file_name)
                    print(f"  Deleted file: {file_name}")
                except Exception as e:
                    print(f"  Warning: could not delete file {file_name}: {e}")

            # Delete test store with force=True (deletes all documents too)
            await client.aio.file_search_stores.delete(
                name=test_store_name,
                config=genai_types.DeleteFileSearchStoreConfig(force=True),
            )
            print(f"  Deleted test store: {test_store_name}")
        except Exception as e:
            print(f"  ERROR deleting test store: {e}")
            print(f"  MANUAL CLEANUP REQUIRED: delete store {test_store_name}")

    # Verify test store is gone
    store_deleted = True
    try:
        stores = await client.aio.file_search_stores.list()
        async for store in stores:
            if getattr(store, "display_name", None) == TEST_STORE_DISPLAY_NAME:
                store_deleted = False
                print(f"WARNING: Test store still exists: {store.name}")
                break
        if store_deleted:
            print("  Confirmed: test store deleted")
    except Exception as e:
        print(f"  Warning: could not verify store deletion: {e}")

    conn.close()

    # Print summary
    print(f"\n{'='*70}")
    print("  Results Summary")
    print(f"{'='*70}")

    # Group by condition
    conditions = {}
    for r in results:
        cond = r.get("condition", "?")
        if cond not in conditions:
            conditions[cond] = {"total": 0, "found": 0, "errors": 0}
        if "error" in r:
            conditions[cond]["errors"] += 1
        else:
            conditions[cond]["total"] += 1
            if r.get("found"):
                conditions[cond]["found"] += 1

    print(f"\n{'Condition':<12} {'Found':>6} {'Total':>6} {'Hit Rate':>10} {'Errors':>8}")
    print("-" * 50)
    for cond, stats in sorted(conditions.items()):
        total = stats["total"]
        found = stats["found"]
        rate = f"{found/total*100:.0f}%" if total > 0 else "N/A"
        print(f"{cond:<12} {found:>6} {total:>6} {rate:>10} {stats['errors']:>8}")

    print(f"\nProd store: {prod_doc_count_before} -> {prod_doc_count_after}")
    print(f"Test store deleted: {store_deleted}")
    duration = time.time() - start_time
    print(f"Duration: {duration:.0f}s")

    return results, prod_doc_count_before, prod_doc_count_after


def main():
    results, prod_before, prod_after = asyncio.run(run_intervention_test())

    # Write results to JSON for post-processing
    output_path = Path(__file__).resolve().parent.parent / ".planning" / "phases" / "16.3-retrievability-research" / "intervention-results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "results": results,
        "production_doc_count_before": prod_before,
        "production_doc_count_after": prod_after,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults written to: {output_path}")


if __name__ == "__main__":
    main()
