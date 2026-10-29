"""Objective video quality inspection engine using FFmpeg metrics.

Computes visual quality scores comparing an encoded video against its source reference:
- VMAF (Video Multi-Method Assessment Fusion - Netflix standard)
- SSIM (Structural Similarity Index)
- PSNR (Peak Signal-to-Noise Ratio)
"""
import json
import os
import re
import subprocess
import time
from typing import Dict, Tuple

from core.config_manager import get_binary_path


def compute_video_quality(
    reference_path: str,
    distorted_path: str,
    metric: str = "ssim"
) -> Tuple[bool, Dict[str, float], str]:
    """Runs dual-input comparison filter graph against reference and distorted video.

    Returns:
        (success, scores_dict, log_output)
    """
    if not os.path.exists(reference_path) or not os.path.exists(distorted_path):
        return False, {}, "Reference or distorted file path does not exist."

    ffmpeg_bin = get_binary_path("ffmpeg")

    # Select filter according to requested metric
    metric_lower = metric.lower()
    vmaf_json_path = os.path.join("/tmp", f"vmaf_result_{os.getpid()}_{int(time.time() if 'time' in globals() else 0)}.json")
    if "vmaf" in metric_lower:
        filter_str = f"[1:v][0:v]libvmaf=log_fmt=json:log_path={vmaf_json_path}"
    elif "psnr" in metric_lower:
        filter_str = "[1:v][0:v]psnr"
    else:  # default ssim
        filter_str = "[1:v][0:v]ssim"

    cmd = [
        ffmpeg_bin, "-hide_banner",
        "-i", reference_path,
        "-i", distorted_path,
        "-lavfi", filter_str,
        "-f", "null",
        "-"
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120
        )
        out = proc.stdout
        scores = {}

        # Parse SSIM
        ssim_match = re.search(r"All:([0-9\.]+)", out)
        if ssim_match:
            scores["ssim"] = float(ssim_match.group(1))

        # Parse PSNR
        psnr_match = re.search(r"average:([0-9\.]+)", out)
        if psnr_match:
            scores["psnr"] = float(psnr_match.group(1))

        # Parse VMAF json if present
        if os.path.exists(vmaf_json_path):
            try:
                with open(vmaf_json_path, "r", encoding="utf-8") as f:
                    v_data = json.load(f)
                v_score = v_data.get("pooled_metrics", {}).get("vmaf", {}).get("mean")
                if v_score is not None:
                    scores["vmaf"] = float(v_score)
                os.remove(vmaf_json_path)
            except Exception:
                pass

        return True, scores, out[-1000:]
    except subprocess.TimeoutExpired:
        return False, {}, "Quality measurement timed out after 120 seconds."
    except Exception as e:
        return False, {}, str(e)
