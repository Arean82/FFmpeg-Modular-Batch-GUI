"""Output file size estimation based on media duration and FFmpeg arguments."""
import re

def estimate_size_mb(duration_sec: float, args: str) -> float | None:
    """Estimates output file size in MB from duration and bitrate flags in args.
    
    Checks for video bitrate (-b:v) and audio bitrate (-b:a).
    """
    if not duration_sec or duration_sec <= 0:
        return None

    v = re.search(r"-b:v\s+(\d+)(k|m)?", args, re.IGNORECASE)
    a = re.search(r"-b:a\s+(\d+)(k|m)?", args, re.IGNORECASE)

    if not v:
        return None

    v_val = int(v.group(1))
    v_unit = (v.group(2) or "k").lower()
    v_kbps = v_val * 1000 if v_unit == "m" else v_val

    if a:
        a_val = int(a.group(1))
        a_unit = (a.group(2) or "k").lower()
        a_kbps = a_val * 1000 if a_unit == "m" else a_val
    else:
        a_kbps = 128

    total_kbps = v_kbps + a_kbps
    mb = (total_kbps * duration_sec) / 8 / 1024
    return round(mb, 2)
