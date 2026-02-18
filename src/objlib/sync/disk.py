"""Disk availability detection for the Objectivism Library.

Provides multi-layer mount checking per locked decision #2:
1. Verify mount_point is a directory
2. Verify mount_point is accessible (listable)
3. Verify library_root exists within mount
"""

from __future__ import annotations

import os
from typing import Literal


def check_disk_availability(
    library_root: str,
    mount_point: str = "/Volumes/U32 Shadow",
) -> Literal["available", "unavailable", "degraded"]:
    """Check if the library disk is accessible.

    Per locked decision #2, uses multi-layer mount check:
    1. Verify mount_point is a directory (os.path.isdir)
    2. Verify mount_point is accessible (os.listdir)
    3. Verify library_root exists within mount (os.path.isdir)

    Args:
        library_root: Full path to the library directory on the mounted disk.
        mount_point: Mount point to check for disk presence.

    Returns:
        'available' -- disk mounted and library path exists
        'unavailable' -- disk not mounted or inaccessible
        'degraded' -- disk mounted but library_root not found
    """
    if not os.path.isdir(mount_point):
        return "unavailable"
    try:
        os.listdir(mount_point)
    except OSError:
        return "unavailable"
    if not os.path.isdir(library_root):
        return "degraded"
    return "available"


def disk_error_message(
    availability: Literal["available", "unavailable", "degraded"],
    library_root: str,
    command: str,
) -> str | None:
    """Return a user-facing error message for disk unavailability, or None if available.

    Args:
        availability: Result from check_disk_availability().
        library_root: Library path for inclusion in error messages.
        command: CLI command name for retry suggestion.

    Returns:
        Human-readable error string, or None if disk is available.
    """
    if availability == "available":
        return None
    if availability == "unavailable":
        return (
            f"Library disk not connected.\n"
            f"  Expected mount: /Volumes/U32 Shadow\n"
            f"  Action: Connect the USB drive and try '{command}' again."
        )
    # degraded
    return (
        f"Library disk is mounted but library path not found.\n"
        f"  Expected: {library_root}\n"
        f"  Action: Verify the library directory exists on the mounted drive."
    )
