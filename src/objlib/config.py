"""Configuration loading and validation for the scanner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScannerConfig:
    """Scanner configuration with sensible defaults matching user decisions."""

    library_path: Path
    db_path: Path = field(default_factory=lambda: Path("data/library.db"))
    allowed_extensions: set[str] = field(
        default_factory=lambda: {".txt", ".md", ".pdf", ".epub", ".docx", ".html"}
    )
    min_file_size: int = 1024  # 1 KB minimum
    skip_hidden: bool = True
    skip_patterns: set[str] = field(
        default_factory=lambda: {".DS_Store", "Thumbs.db", ".git", "__pycache__"}
    )
    follow_symlinks: bool = True

    def __post_init__(self) -> None:
        """Ensure paths are Path objects."""
        if isinstance(self.library_path, str):
            self.library_path = Path(self.library_path)
        if isinstance(self.db_path, str):
            self.db_path = Path(self.db_path)


def load_config(config_path: Path) -> ScannerConfig:
    """Load scanner configuration from JSON, merging with defaults.

    Args:
        config_path: Path to scanner_config.json

    Returns:
        ScannerConfig with values from file merged over defaults.
    """
    with open(config_path) as f:
        data = json.load(f)

    kwargs: dict[str, object] = {}

    if "library_path" in data:
        kwargs["library_path"] = Path(data["library_path"])
    else:
        kwargs["library_path"] = Path("/Volumes/U32 Shadow/Objectivism Library")

    if "db_path" in data:
        kwargs["db_path"] = Path(data["db_path"])

    if "allowed_extensions" in data:
        kwargs["allowed_extensions"] = set(data["allowed_extensions"])

    if "min_file_size_bytes" in data:
        kwargs["min_file_size"] = data["min_file_size_bytes"]

    if "skip_hidden_files" in data:
        kwargs["skip_hidden"] = data["skip_hidden_files"]

    if "skip_patterns" in data:
        kwargs["skip_patterns"] = set(data["skip_patterns"])

    if "follow_symlinks" in data:
        kwargs["follow_symlinks"] = data["follow_symlinks"]

    return ScannerConfig(**kwargs)


def load_metadata_mappings(mappings_path: Path) -> dict:
    """Load metadata mappings from JSON.

    Args:
        mappings_path: Path to metadata_mappings.json

    Returns:
        Dictionary with course metadata mappings and folder patterns.
    """
    with open(mappings_path) as f:
        return json.load(f)
