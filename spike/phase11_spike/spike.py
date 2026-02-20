"""Phase 11 spike runner: SDK inspection + round-trip display_name test + import lag measurement.

Execute with: python -m spike.phase11_spike.spike

Five phases:
1. SDK Source Inspection -- collect evidence about display_name serialization path
2. Test Store Setup -- create dedicated Gemini store + generate test corpus
3. Round-Trip + Lag Measurement -- upload files, import to store, measure visibility lag
4. Statistics + Report -- compute P50/P95/P99, summarize round-trip results
5. Cleanup -- delete test store and all uploaded files
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from typing import Any, Optional

import keyring
from google import genai

from spike.phase11_spike.lag_measurement import compute_percentiles, measure_visibility_lag
from spike.phase11_spike.sdk_inspector import collect_sdk_evidence
from spike.phase11_spike.test_corpus import create_test_corpus


def _print_header(phase_num: int, title: str) -> None:
    """Print a formatted phase header."""
    print(f"\n{'='*70}")
    print(f"  Phase {phase_num}: {title}")
    print(f"{'='*70}\n")


def _print_sdk_evidence(evidence: dict[str, Any]) -> None:
    """Print SDK evidence in a structured format."""
    print(f"SDK Version: {evidence['sdk_version']}")
    for section_key, label in [
        ("files_py", "files.py"),
        ("types_py", "types.py"),
        ("common_py", "_common.py"),
    ]:
        section = evidence[section_key]
        print(f"\n  {label}: {section['path']}")
        for line_info in section["lines"]:
            print(f"    Line {line_info['line_no']:>5}: {line_info['content']}")
            print(f"             -> {line_info['description']}")

    print(f"\n  Conclusion: {evidence['conclusion']}")


async def _wait_for_file_active(
    client: genai.Client,
    file_name: str,
    timeout: float = 60.0,
) -> Any:
    """Poll Files API until file state is ACTIVE.

    Args:
        client: Gemini API client.
        file_name: File resource name (e.g., "files/abc123").
        timeout: Maximum wait time in seconds.

    Returns:
        The File object once ACTIVE.

    Raises:
        TimeoutError: If file does not become ACTIVE within timeout.
        RuntimeError: If file state becomes FAILED.
    """
    start = time.perf_counter()
    interval = 0.5
    while True:
        file_obj = await client.aio.files.get(name=file_name)
        state_str = str(file_obj.state) if file_obj.state else "UNKNOWN"

        if "ACTIVE" in state_str:
            return file_obj
        if "FAILED" in state_str:
            raise RuntimeError(f"File {file_name} entered FAILED state")

        elapsed = time.perf_counter() - start
        if elapsed >= timeout:
            raise TimeoutError(
                f"File {file_name} not ACTIVE after {timeout}s (state={state_str})"
            )

        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 5.0)


async def _wait_for_import_done(
    client: genai.Client,
    operation: Any,
    timeout: float = 120.0,
) -> Any:
    """Poll import operation until done.

    Args:
        client: Gemini API client.
        operation: ImportFileOperation from import_file().
        timeout: Maximum wait time in seconds.

    Returns:
        The completed operation object.

    Raises:
        TimeoutError: If operation does not complete within timeout.
        RuntimeError: If operation completes with an error.
    """
    start = time.perf_counter()
    interval = 0.5

    # Check if already done
    if operation.done:
        if operation.error:
            raise RuntimeError(f"Import operation failed: {operation.error}")
        return operation

    op_name = operation.name
    if not op_name:
        raise RuntimeError("Import operation has no name for polling")

    while True:
        elapsed = time.perf_counter() - start
        if elapsed >= timeout:
            raise TimeoutError(
                f"Import operation {op_name} not done after {timeout}s"
            )

        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 5.0)

        # Poll the operation using the raw API client
        # The operations.get returns a raw dict, so we need to parse it
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
            # Re-fetch the operation to get the typed response
            # Parse the response dict to extract document_name
            resp = response_dict.get("response", {})
            document_name = resp.get("documentName")
            return type("CompletedOp", (), {
                "done": True,
                "error": None,
                "name": op_name,
                "response": type("Resp", (), {
                    "document_name": document_name,
                    "parent": resp.get("parent"),
                })(),
            })()


async def run_spike() -> dict[str, Any]:
    """Execute the full Phase 11 spike.

    Returns:
        Dict with all results for RESULTS.md generation.
    """
    all_results: dict[str, Any] = {}
    uploaded_files: list[str] = []  # File resource names for cleanup
    store_name: Optional[str] = None
    temp_dir: Optional[str] = None
    client: Optional[genai.Client] = None

    try:
        # =====================================================================
        # Phase 1: SDK Source Inspection
        # =====================================================================
        _print_header(1, "SDK Source Inspection")

        evidence = collect_sdk_evidence()
        _print_sdk_evidence(evidence)
        all_results["sdk_evidence"] = evidence

        # =====================================================================
        # Phase 2: Test Store Setup
        # =====================================================================
        _print_header(2, "Test Store Setup")

        api_key = keyring.get_password("objlib-gemini", "api_key")
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No API key found. Set via keyring or GEMINI_API_KEY env var."
            )

        client = genai.Client(api_key=api_key)
        print("  Gemini client created")

        # Create dedicated test store
        store = await client.aio.file_search_stores.create(
            config={"display_name": "phase11-spike-test"}
        )
        store_name = store.name
        print(f"  Test store created: {store_name}")

        # Generate test corpus
        temp_dir = tempfile.mkdtemp(prefix="phase11_spike_")
        test_files = create_test_corpus(temp_dir)
        total_size = sum(f["size_bytes"] for f in test_files)
        print(f"  Test corpus: {len(test_files)} files, {total_size:,} bytes total")
        print(f"  Temp dir: {temp_dir}")

        all_results["store_name"] = store_name
        all_results["test_file_count"] = len(test_files)

        # =====================================================================
        # Phase 3: Round-Trip + Lag Measurement
        # =====================================================================
        _print_header(3, "Round-Trip + Lag Measurement")

        measurements: list[dict[str, Any]] = []

        for file_info in test_files:
            idx = file_info["index"]
            display_name = file_info["display_name"]
            dn_preview = display_name[:50] + ("..." if len(display_name) > 50 else "")
            print(f"\n  [{idx+1:2d}/14] display_name={dn_preview!r}")
            print(f"         size={file_info['size_bytes']:,} bytes ({file_info['size_bucket']})")

            record: dict[str, Any] = {
                "index": idx,
                "display_name_submitted": display_name,
                "size_bytes": file_info["size_bytes"],
                "size_bucket": file_info["size_bucket"],
                "category": file_info["category"],
                "error": None,
            }

            try:
                # Step 1: Upload file to Files API
                print("         Uploading to Files API...", end="", flush=True)
                uploaded_file = await client.aio.files.upload(
                    file=file_info["local_path"],
                    config={"display_name": display_name},
                )
                uploaded_files.append(uploaded_file.name)
                print(f" {uploaded_file.name}")

                # Step 2: Wait for file to become ACTIVE
                print("         Waiting for ACTIVE...", end="", flush=True)
                active_file = await _wait_for_file_active(client, uploaded_file.name)
                file_display_name = active_file.display_name
                print(f" state={active_file.state}")

                # Step 3: Import to store
                print("         Importing to store...", end="", flush=True)
                import_op = await client.aio.file_search_stores.import_file(
                    file_search_store_name=store_name,
                    file_name=uploaded_file.name,
                )
                print(f" op={import_op.name}")

                # Step 4: Wait for import to complete
                print("         Waiting for import...", end="", flush=True)
                completed_op = await _wait_for_import_done(client, import_op)
                document_name = None
                if completed_op.response:
                    raw_doc_name = completed_op.response.document_name
                    # The API returns just the doc ID (e.g., "abc-xyz").
                    # Construct the full resource path for documents.get().
                    if raw_doc_name:
                        if "/" in raw_doc_name:
                            # Already a full resource path
                            document_name = raw_doc_name
                        else:
                            # Just the doc ID -- prepend store path
                            document_name = f"{store_name}/documents/{raw_doc_name}"
                print(f" document={document_name}")

                if not document_name:
                    # Fallback: list documents and find by file name
                    # Note: Document.display_name is the file ID, not the
                    # submitted display_name. Match on file_name prefix instead.
                    print("         Fallback: listing documents to find match...")
                    file_id = uploaded_file.name.replace("files/", "")
                    pager = await client.aio.file_search_stores.documents.list(
                        parent=store_name
                    )
                    async for doc in pager:
                        if doc.display_name == file_id or (doc.name and file_id in doc.name):
                            document_name = doc.name
                            break
                    if document_name:
                        print(f"         Found via list: {document_name}")
                    else:
                        raise RuntimeError("Could not find imported document")

                # Step 5: Measure visibility lag
                print("         Measuring visibility lag...", end="", flush=True)
                visibility_start = time.perf_counter()
                lag_result = await measure_visibility_lag(
                    client,
                    store_name,
                    document_name,
                    max_wait=300.0,
                    initial_interval=0.5,
                    backoff_factor=1.5,
                    max_interval=10.0,
                )
                print(
                    f" get={lag_result['lag_to_get_seconds']:.3f}s"
                    f" list={lag_result['lag_to_list_seconds']:.3f}s"
                    if lag_result["lag_to_get_seconds"] is not None
                    and lag_result["lag_to_list_seconds"] is not None
                    else f" timed_out={lag_result['timed_out']}"
                )

                # Step 6: Compare display_names
                doc_display_name = None
                if lag_result.get("document"):
                    doc_obj = lag_result["document"]
                    doc_display_name = doc_obj.display_name if hasattr(doc_obj, "display_name") else None

                exact_file_match = file_display_name == display_name
                exact_doc_match = doc_display_name == display_name if doc_display_name is not None else None

                print(f"         File.display_name  = {file_display_name!r} (match={exact_file_match})")
                print(f"         Doc.display_name   = {doc_display_name!r} (match={exact_doc_match})")

                record.update(
                    {
                        "file_name": uploaded_file.name,
                        "document_name": document_name,
                        "file_display_name": file_display_name,
                        "doc_display_name": doc_display_name,
                        "exact_file_match": exact_file_match,
                        "exact_doc_match": exact_doc_match,
                        "lag_to_get_seconds": lag_result["lag_to_get_seconds"],
                        "lag_to_list_seconds": lag_result["lag_to_list_seconds"],
                        "document_state": lag_result["document_state"],
                        "timed_out": lag_result["timed_out"],
                        "polls_count": lag_result["polls_count"],
                    }
                )

            except Exception as e:
                print(f"\n         ERROR: {e}")
                record["error"] = str(e)

            measurements.append(record)

            # Rate limit protection
            await asyncio.sleep(1.0)

        all_results["measurements"] = measurements

        # =====================================================================
        # Phase 4: Statistics + Report
        # =====================================================================
        _print_header(4, "Statistics + Report")

        # Filter successful measurements
        successful = [m for m in measurements if m.get("error") is None]
        failed = [m for m in measurements if m.get("error") is not None]

        print(f"  Successful: {len(successful)}/{len(measurements)}")
        print(f"  Failed: {len(failed)}/{len(measurements)}")

        if failed:
            print("\n  Failed files:")
            for m in failed:
                print(f"    [{m['index']}] {m['display_name_submitted'][:40]}: {m['error']}")

        # Display_name round-trip analysis
        file_exact = sum(1 for m in successful if m.get("exact_file_match"))
        doc_exact = sum(1 for m in successful if m.get("exact_doc_match"))
        print(f"\n  Display Name Round-Trip:")
        print(f"    File.display_name exact matches: {file_exact}/{len(successful)}")
        print(f"    Doc.display_name exact matches:  {doc_exact}/{len(successful)}")

        # Mismatches detail
        file_mismatches = [m for m in successful if not m.get("exact_file_match")]
        doc_mismatches = [m for m in successful if not m.get("exact_doc_match")]
        if file_mismatches:
            print("\n  File.display_name mismatches:")
            for m in file_mismatches:
                print(f"    [{m['index']}] submitted={m['display_name_submitted']!r}")
                print(f"          returned={m['file_display_name']!r}")
        if doc_mismatches:
            print("\n  Doc.display_name mismatches:")
            for m in doc_mismatches:
                print(f"    [{m['index']}] submitted={m['display_name_submitted']!r}")
                print(f"          returned={m['doc_display_name']!r}")

        # Latency statistics
        get_lags = [
            m["lag_to_get_seconds"]
            for m in successful
            if m.get("lag_to_get_seconds") is not None
        ]
        list_lags = [
            m["lag_to_list_seconds"]
            for m in successful
            if m.get("lag_to_list_seconds") is not None
        ]

        stats: dict[str, Any] = {}

        if get_lags:
            get_stats = compute_percentiles(get_lags)
            stats["get_overall"] = get_stats
            print(f"\n  Visibility Lag (documents.get):")
            print(f"    N={get_stats['n']}, P50={get_stats.get('p50', 'N/A')}s, "
                  f"P95={get_stats.get('p95', 'N/A')}s, P99={get_stats.get('p99', 'N/A')}s")
            print(f"    min={get_stats['min']}s, max={get_stats['max']}s, "
                  f"mean={get_stats['mean']}s, stdev={get_stats.get('stdev', 'N/A')}s")

        if list_lags:
            list_stats = compute_percentiles(list_lags)
            stats["list_overall"] = list_stats
            print(f"\n  Visibility Lag (documents.list):")
            print(f"    N={list_stats['n']}, P50={list_stats.get('p50', 'N/A')}s, "
                  f"P95={list_stats.get('p95', 'N/A')}s, P99={list_stats.get('p99', 'N/A')}s")
            print(f"    min={list_stats['min']}s, max={list_stats['max']}s, "
                  f"mean={list_stats['mean']}s, stdev={list_stats.get('stdev', 'N/A')}s")

        # By size bucket
        for method_name, lags_key in [("get", "lag_to_get_seconds"), ("list", "lag_to_list_seconds")]:
            bucket_stats: dict[str, Any] = {}
            for bucket in ["1KB", "10KB", "50KB", "100KB"]:
                bucket_lags = [
                    m[lags_key]
                    for m in successful
                    if m.get(lags_key) is not None and m["size_bucket"] == bucket
                ]
                if bucket_lags:
                    bucket_stats[bucket] = compute_percentiles(bucket_lags)

            if bucket_stats:
                stats[f"{method_name}_by_bucket"] = bucket_stats
                print(f"\n  Lag by size bucket (documents.{method_name}):")
                for bucket, bs in bucket_stats.items():
                    print(f"    {bucket:>5}: N={bs['n']}, P50={bs.get('p50', 'N/A')}s, "
                          f"mean={bs['mean']}s, max={bs['max']}s")

        all_results["stats"] = stats
        all_results["summary"] = {
            "total_files": len(measurements),
            "successful": len(successful),
            "failed": len(failed),
            "file_exact_matches": file_exact,
            "doc_exact_matches": doc_exact,
            "file_mismatches": [
                {
                    "index": m["index"],
                    "submitted": m["display_name_submitted"],
                    "returned": m["file_display_name"],
                }
                for m in file_mismatches
            ],
            "doc_mismatches": [
                {
                    "index": m["index"],
                    "submitted": m["display_name_submitted"],
                    "returned": m["doc_display_name"],
                }
                for m in doc_mismatches
            ],
        }

    finally:
        # =====================================================================
        # Phase 5: Cleanup
        # =====================================================================
        _print_header(5, "Cleanup")

        if client and store_name:
            # Delete test store (force=True deletes all documents too)
            try:
                await client.aio.file_search_stores.delete(
                    name=store_name,
                    config={"force": True},
                )
                print(f"  Deleted test store: {store_name}")
            except Exception as e:
                print(f"  Warning: failed to delete store {store_name}: {e}")

        if client and uploaded_files:
            # Delete uploaded files from Files API
            deleted = 0
            for file_name in uploaded_files:
                try:
                    await client.aio.files.delete(name=file_name)
                    deleted += 1
                except Exception:
                    pass  # Files may have already expired or been deleted
            print(f"  Deleted {deleted}/{len(uploaded_files)} files from Files API")

        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print(f"  Removed temp directory: {temp_dir}")

    return all_results


def main() -> None:
    """Entry point for spike execution."""
    print("Phase 11 Spike: display_name Stability + Import Lag Measurement")
    print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    start_time = time.perf_counter()
    results = asyncio.run(run_spike())
    elapsed = time.perf_counter() - start_time

    print(f"\n{'='*70}")
    print(f"  Spike complete in {elapsed:.1f}s")
    print(f"{'='*70}")

    # Write raw results to JSON for debugging
    json_path = os.path.join(
        os.path.dirname(__file__), "raw_results.json"
    )
    # Serialize results (skip non-serializable objects)
    serializable = {}
    for k, v in results.items():
        if k == "measurements":
            serializable[k] = [
                {mk: mv for mk, mv in m.items() if mk != "document"}
                for m in v
            ]
        elif k == "sdk_evidence":
            serializable[k] = v
        elif isinstance(v, (str, int, float, bool, list, dict, type(None))):
            serializable[k] = v

    with open(json_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"\nRaw results written to: {json_path}")


if __name__ == "__main__":
    main()
