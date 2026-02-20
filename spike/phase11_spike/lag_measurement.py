"""Import-to-visible lag measurement with exponential backoff polling.

Measures how long after import_file() completes until the document
is visible via documents.get() and documents.list().
"""

from __future__ import annotations

import asyncio
import math
import statistics
import time
from typing import Any, Optional


async def measure_visibility_lag(
    client: Any,
    store_name: str,
    document_name: str,
    *,
    max_wait: float = 300.0,
    initial_interval: float = 0.5,
    backoff_factor: float = 1.5,
    max_interval: float = 10.0,
) -> dict[str, Any]:
    """Measure lag from import completion to document visibility.

    Polls using two methods:
    1. documents.get(name=document_name) -- O(1) lookup
    2. documents.list(parent=store_name) -- scan for document

    Records when each method first succeeds.

    Args:
        client: google.genai.Client instance.
        store_name: Full store resource name (e.g., "fileSearchStores/abc123").
        document_name: Full document resource name from import operation response.
        max_wait: Maximum seconds to wait before declaring timeout.
        initial_interval: Initial polling interval in seconds.
        backoff_factor: Multiplier for exponential backoff.
        max_interval: Maximum polling interval in seconds.

    Returns:
        Dict with lag_to_get_seconds, lag_to_list_seconds, document_state,
        timed_out, polls_count, and document (the retrieved Document object if found).
    """
    start = time.perf_counter()
    interval = initial_interval
    polls = 0
    lag_to_get: Optional[float] = None
    lag_to_list: Optional[float] = None
    document_state: Optional[str] = None
    found_document: Any = None

    while True:
        elapsed = time.perf_counter() - start
        if elapsed >= max_wait:
            return {
                "lag_to_get_seconds": lag_to_get,
                "lag_to_list_seconds": lag_to_list,
                "document_state": document_state,
                "timed_out": True,
                "polls_count": polls,
                "document": found_document,
            }

        polls += 1

        # Method 1: documents.get() -- O(1) check
        if lag_to_get is None:
            try:
                doc = await client.aio.file_search_stores.documents.get(
                    name=document_name
                )
                lag_to_get = time.perf_counter() - start
                document_state = str(doc.state) if doc.state else None
                found_document = doc
            except Exception:
                pass  # Not visible yet via get

        # Method 2: documents.list() -- scan check
        if lag_to_list is None:
            try:
                pager = await client.aio.file_search_stores.documents.list(
                    parent=store_name
                )
                async for doc in pager:
                    if doc.name == document_name:
                        lag_to_list = time.perf_counter() - start
                        if document_state is None:
                            document_state = str(doc.state) if doc.state else None
                        if found_document is None:
                            found_document = doc
                        break
            except Exception:
                pass  # Not visible yet via list

        # If both methods succeeded, we are done
        if lag_to_get is not None and lag_to_list is not None:
            return {
                "lag_to_get_seconds": lag_to_get,
                "lag_to_list_seconds": lag_to_list,
                "document_state": document_state,
                "timed_out": False,
                "polls_count": polls,
                "document": found_document,
            }

        # Exponential backoff
        await asyncio.sleep(interval)
        interval = min(interval * backoff_factor, max_interval)


def compute_percentiles(latencies: list[float]) -> dict[str, Any]:
    """Compute P50/P95/P99 percentile statistics from a list of latencies.

    Args:
        latencies: List of latency values in seconds.

    Returns:
        Dict with n, min, p50, p95, p99, max, mean, stdev (all rounded to 3dp).
        Returns error dict if list is empty.
    """
    if not latencies:
        return {"error": "No latency data", "n": 0}

    n = len(latencies)
    sorted_lats = sorted(latencies)

    result: dict[str, Any] = {
        "n": n,
        "min": round(sorted_lats[0], 3),
        "max": round(sorted_lats[-1], 3),
        "mean": round(statistics.mean(sorted_lats), 3),
    }

    if n >= 2:
        result["stdev"] = round(statistics.stdev(sorted_lats), 3)
    else:
        result["stdev"] = 0.0

    if n >= 4:
        # Use statistics.quantiles for N >= 4
        quantiles = statistics.quantiles(sorted_lats, n=100)
        result["p50"] = round(quantiles[49], 3)  # 50th percentile
        result["p95"] = round(quantiles[94], 3)  # 95th percentile
        result["p99"] = round(quantiles[98], 3)  # 99th percentile
    elif n >= 1:
        # Fallback: use median for p50, max for p95/p99
        result["p50"] = round(statistics.median(sorted_lats), 3)
        if n >= 2:
            # Linear interpolation approximation
            result["p95"] = round(sorted_lats[-1], 3)
            result["p99"] = round(sorted_lats[-1], 3)
        else:
            result["p95"] = result["p50"]
            result["p99"] = result["p50"]

    return result
