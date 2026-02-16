"""Data models and enums for the Objectivism Library scanner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class FileStatus(str, Enum):
    """Status of a file in the processing pipeline."""

    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"
    LOCAL_DELETE = "LOCAL_DELETE"


class MetadataQuality(str, Enum):
    """Quality grade for extracted metadata."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    MINIMAL = "minimal"
    NONE = "none"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class FileRecord:
    """Represents a file in the library with its metadata and state."""

    file_path: str
    content_hash: str
    filename: str
    file_size: int
    metadata_json: str | None = None
    metadata_quality: MetadataQuality = MetadataQuality.UNKNOWN
    status: FileStatus = FileStatus.PENDING

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary with enum values as strings."""
        d = asdict(self)
        d["metadata_quality"] = self.metadata_quality.value
        d["status"] = self.status.value
        return d


class OperationState(str, Enum):
    """State of an upload operation tracked in the upload_operations table."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class UploadConfig:
    """Configuration for the Gemini File Search upload pipeline.

    Controls store targeting, concurrency limits, polling behavior,
    rate limiting, and crash recovery timeouts.
    """

    store_name: str
    api_key: str | None = None
    max_concurrent_uploads: int = 7
    max_concurrent_polls: int = 20
    batch_size: int = 150
    poll_timeout_seconds: int = 3600
    poll_min_wait: int = 5
    poll_max_wait: int = 60
    rate_limit_tier: str = "tier1"
    recovery_timeout_seconds: int = 14400
    db_path: str = "data/library.db"
