"""Mistral Batch API client for bulk metadata extraction.

Implements Mistral's async Batch API for high-volume, cost-effective extraction:
- 50% lower cost than synchronous calls
- No rate limiting issues (Mistral processes at their pace)
- Supports up to 1 million requests per batch (10k inline, rest via file upload)
- Perfect for offline bulk processing

Workflow:
1. Build batch requests (JSONL format)
2. Submit batch job to Mistral
3. Poll for completion (async, non-blocking)
4. Download and parse results
5. Update database with extracted metadata

Usage:
    client = MistralBatchClient(api_key="...")
    batch_id = await client.submit_batch(requests, job_name="wave2-extraction")

    # Poll for completion
    while not await client.is_complete(batch_id):
        await asyncio.sleep(30)

    # Download results
    results = await client.download_results(batch_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mistralai import Mistral
from mistralai.models.sdkerror import SDKError

logger = logging.getLogger(__name__)


@dataclass
class BatchRequest:
    """Single request in a batch job.

    Attributes:
        custom_id: Unique identifier for this request (e.g., file_path).
        method: HTTP method (always "POST" for chat completions).
        url: Endpoint path (e.g., "/v1/chat/completions").
        body: Request payload (model, messages, temperature, etc.).
    """

    custom_id: str
    method: str
    url: str
    body: dict[str, Any]

    def to_jsonl_line(self) -> str:
        """Convert to JSONL line format for batch submission."""
        return json.dumps({
            "custom_id": self.custom_id,
            "method": self.method,
            "url": self.url,
            "body": self.body,
        })


@dataclass
class BatchResult:
    """Single result from a batch job.

    Attributes:
        custom_id: Original request identifier.
        response: Response body (parsed JSON from response.body).
        error: Error information if request failed.
    """

    custom_id: str
    response: dict[str, Any] | None
    error: dict[str, Any] | None

    @classmethod
    def from_jsonl_line(cls, line: str) -> "BatchResult":
        """Parse JSONL result line.

        Response structure from Mistral:
        {
            "custom_id": "...",
            "response": {
                "body": {...actual API response...},
                "status_code": 200
            },
            "error": {...} (if failed)
        }
        """
        data = json.loads(line)

        # Extract response body if present
        response_data = data.get("response")
        response_body = None
        if response_data and isinstance(response_data, dict):
            response_body = response_data.get("body")

        return cls(
            custom_id=data["custom_id"],
            response=response_body,
            error=data.get("error"),
        )


class MistralBatchClient:
    """Async client for Mistral Batch API.

    Handles batch job submission, polling, and result retrieval for
    bulk metadata extraction workloads.

    Args:
        api_key: Mistral API key.
        model: Model identifier (default: magistral-medium-latest).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "magistral-medium-latest",
    ) -> None:
        self._client = Mistral(api_key=api_key)
        self._model = model

    async def submit_batch(
        self,
        requests: list[BatchRequest],
        job_name: str | None = None,
        metadata: dict[str, str] | None = None,
        use_inline: bool = False,
    ) -> str:
        """Submit a batch job to Mistral.

        Args:
            requests: List of BatchRequest objects to process.
            job_name: Optional descriptive name for the job.
            metadata: Optional metadata dict (key-value pairs).
            use_inline: If True and <=10k requests, use inline batching
                (skips file upload). Default: False (always use file upload).

        Returns:
            Batch job ID for polling and retrieval.

        Raises:
            SDKError: On API errors.
            ValueError: If requests list is empty or exceeds limits.
        """
        if not requests:
            raise ValueError("Cannot submit empty batch")

        if use_inline and len(requests) > 10_000:
            raise ValueError(
                f"Inline batches limited to 10,000 requests (got {len(requests)}). "
                "Use file upload (use_inline=False) for larger batches."
            )

        logger.info(
            "Submitting batch job: %d requests, model=%s, name=%s, inline=%s",
            len(requests),
            self._model,
            job_name or "unnamed",
            use_inline,
        )

        if use_inline:
            # Inline batching (<=10k requests, no file upload)
            request_dicts = [
                {
                    "custom_id": req.custom_id,
                    "body": req.body,
                }
                for req in requests
            ]

            batch_job = await self._client.batch.jobs.create_async(
                requests=request_dicts,
                model=self._model,
                endpoint="/v1/chat/completions",
                metadata=metadata or {},
            )

            logger.info(
                "Batch job created (inline): %s (status=%s)",
                batch_job.id,
                batch_job.status,
            )
        else:
            # File-based batching (supports up to 1M requests)
            # Build JSONL content
            jsonl_lines = [req.to_jsonl_line() for req in requests]
            jsonl_content = "\n".join(jsonl_lines)

            # Upload input file
            # Note: file parameter is a dict with file_name and content (bytes)
            input_file = await self._client.files.upload_async(
                file={
                    "file_name": f"{job_name or 'batch'}.jsonl",
                    "content": jsonl_content.encode("utf-8"),
                },
                purpose="batch",
            )

            logger.info("Uploaded input file: %s (%d bytes)", input_file.id, len(jsonl_content))

            # Create batch job
            batch_job = await self._client.batch.jobs.create_async(
                input_files=[input_file.id],
                model=self._model,
                endpoint="/v1/chat/completions",
                metadata=metadata or {},
            )

            logger.info(
                "Batch job created (file): %s (status=%s)",
                batch_job.id,
                batch_job.status,
            )

        return batch_job.id

    async def get_status(self, batch_id: str) -> dict[str, Any]:
        """Get current status of a batch job.

        Args:
            batch_id: Batch job ID from submit_batch().

        Returns:
            Status dict with keys: id, status, created_at, completed_at,
            request_counts (total, completed, failed).

        Raises:
            SDKError: On API errors.
        """
        job = await self._client.batch.jobs.get_async(batch_id)

        return {
            "id": job.id,
            "status": job.status,
            "model": job.model,
            "created_at": job.created_at,
            "started_at": getattr(job, "started_at", None),
            "completed_at": getattr(job, "completed_at", None),
            "total_requests": job.total_requests if hasattr(job, "total_requests") else 0,
            "succeeded_requests": getattr(job, "succeeded_requests", 0),
            "failed_requests": getattr(job, "failed_requests", 0),
            "metadata": job.metadata if hasattr(job, "metadata") else {},
        }

    async def is_complete(self, batch_id: str) -> bool:
        """Check if batch job has completed.

        Args:
            batch_id: Batch job ID.

        Returns:
            True if status is SUCCESS, FAILED, CANCELLED, or TIMEOUT_EXCEEDED.
        """
        status = await self.get_status(batch_id)
        return status["status"] in ("SUCCESS", "FAILED", "CANCELLED", "TIMEOUT_EXCEEDED")

    async def wait_for_completion(
        self,
        batch_id: str,
        poll_interval: int = 30,
        timeout: int = 3600,
    ) -> dict[str, Any]:
        """Poll batch job until completion or timeout.

        Args:
            batch_id: Batch job ID.
            poll_interval: Seconds between status checks (default: 30).
            timeout: Maximum seconds to wait (default: 3600 = 1 hour).

        Returns:
            Final status dict.

        Raises:
            TimeoutError: If job doesn't complete within timeout.
            RuntimeError: If job status is "failed" or "cancelled".
        """
        elapsed = 0

        while elapsed < timeout:
            status = await self.get_status(batch_id)

            logger.info(
                "Batch %s: %s (%d/%d requests completed)",
                batch_id[:8],
                status["status"],
                status["succeeded_requests"],
                status["total_requests"],
            )

            if status["status"] in ("SUCCESS",):
                logger.info("Batch job completed successfully")
                return status

            if status["status"] == "FAILED":
                raise RuntimeError(f"Batch job failed: {status}")

            if status["status"] in ("CANCELLED", "TIMEOUT_EXCEEDED"):
                raise RuntimeError(f"Batch job {status['status'].lower()}: {status}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(
            f"Batch job {batch_id} did not complete within {timeout}s"
        )

    async def download_results(self, batch_id: str) -> list[BatchResult]:
        """Download and parse results from completed batch job.

        Args:
            batch_id: Batch job ID.

        Returns:
            List of BatchResult objects (one per request).

        Raises:
            SDKError: On API errors.
            RuntimeError: If job is not complete or has no output file.
        """
        # Get job details
        job = await self._client.batch.jobs.get_async(batch_id)

        if job.status != "SUCCESS":
            raise RuntimeError(
                f"Cannot download results: job status is {job.status}"
            )

        if not hasattr(job, "output_file") or not job.output_file:
            raise RuntimeError(f"Batch job {batch_id} has no output file")

        logger.info("Downloading output file: %s", job.output_file)

        # Download output file
        output_content = await self._client.files.download_async(job.output_file)

        # Parse JSONL results
        # Note: Response structure is {custom_id, response: {body: {...}}}
        results = []
        for line in output_content.decode("utf-8").strip().split("\n"):
            if line:  # Skip empty lines
                results.append(BatchResult.from_jsonl_line(line))

        logger.info(
            "Downloaded %d results (succeeded=%d, errors=%d)",
            len(results),
            sum(1 for r in results if r.response),
            sum(1 for r in results if r.error),
        )

        return results

    async def cancel_batch(self, batch_id: str) -> None:
        """Cancel a running batch job.

        Args:
            batch_id: Batch job ID.

        Raises:
            SDKError: On API errors.
        """
        await self._client.batch.jobs.cancel_async(batch_id)
        logger.info("Cancelled batch job: %s", batch_id)

    def build_extraction_request(
        self,
        custom_id: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 1.0,
        max_tokens: int = 8000,
    ) -> BatchRequest:
        """Build a batch request for metadata extraction.

        Args:
            custom_id: Unique identifier (e.g., file_path).
            system_prompt: System prompt for extraction.
            user_prompt: User prompt (transcript content).
            temperature: Sampling temperature (default: 1.0).
            max_tokens: Max response tokens (default: 8000).

        Returns:
            BatchRequest ready for submission.
        """
        return BatchRequest(
            custom_id=custom_id,
            method="POST",
            url="/v1/chat/completions",
            body={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
        )
