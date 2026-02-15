"""Data models and enums for the Objectivism Library scanner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


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
