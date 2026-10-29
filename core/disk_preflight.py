"""Disk space pre-flight validation engine for batch FFmpeg encoding.

Computes aggregate estimated output footprint across all pending queue files
and validates against destination volume available storage.
"""
import os
import shutil
from typing import Dict, List, Tuple


def check_disk_space_preflight(
    queue_items: List[Dict],
    dest_dir: str,
    custom_dest: bool,
    default_dest: str = ""
) -> Tuple[bool, str, Dict[str, float]]:
    """Checks whether the target volume(s) have sufficient disk space for the queue.

    Returns:
        (is_safe, message, stats_dict)
    """
    if not queue_items:
        return True, "Queue is empty.", {"estimated_mb": 0.0, "available_mb": 0.0}

    # Determine effective target folder
    if custom_dest and dest_dir and os.path.isdir(dest_dir):
        effective_dest = os.path.abspath(dest_dir)
    elif default_dest and os.path.isdir(default_dest):
        effective_dest = os.path.abspath(default_dest)
    else:
        # Source directory of the first file
        first_path = queue_items[0].get("path", "")
        effective_dest = os.path.dirname(os.path.abspath(first_path)) if first_path else os.path.expanduser("~")

    try:
        usage = shutil.disk_usage(effective_dest)
        free_bytes = usage.free
    except Exception as e:
        return True, f"Could not query disk space: {e}", {"estimated_mb": 0.0, "available_mb": 0.0}

    # Sum estimated sizes or fallback to input source sizes
    total_est_bytes = 0
    for item in queue_items:
        meta = item.get("meta", {})
        size = meta.get("size", 0)
        # Use source size as conservative estimate if no specific estimate exists
        total_est_bytes += size if size > 0 else 50 * 1024 * 1024  # 50MB default

    free_mb = free_bytes / (1024 * 1024)
    est_mb = total_est_bytes / (1024 * 1024)

    stats = {
        "estimated_mb": est_mb,
        "available_mb": free_mb,
        "free_percent": (free_bytes / usage.total) * 100.0 if usage.total > 0 else 0.0
    }

    # Trigger warning if estimated output exceeds 95% of available space
    if est_mb > (free_mb * 0.95):
        shortage_mb = est_mb - free_mb
        msg = (
            f"Low Disk Space Warning!\n\n"
            f"Destination Volume: {effective_dest}\n"
            f"Estimated Output Size: {est_mb:.1f} MB ({est_mb/1024:.2f} GB)\n"
            f"Available Free Space: {free_mb:.1f} MB ({free_mb/1024:.2f} GB)\n"
            f"Projected Shortage: {shortage_mb:.1f} MB\n\n"
            f"Proceeding may cause conversion failure or incomplete files."
        )
        return False, msg, stats

    return True, f"Sufficient disk space available ({free_mb:.1f} MB free).", stats
