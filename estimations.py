# estimations.py
# Estimate output file size based on duration and FFmpeg args --- Size estimation logic

import re

def estimate_size_mb(duration_sec, args):
    v = re.search(r"-b:v\s+(\d+)k", args)
    a = re.search(r"-b:a\s+(\d+)k", args)

    if not v:
        return None

    v_kbps = int(v.group(1))
    a_kbps = int(a.group(1)) if a else 128

    total_kbps = v_kbps + a_kbps
    mb = (total_kbps * duration_sec) / 8 / 1024
    return round(mb, 2)
