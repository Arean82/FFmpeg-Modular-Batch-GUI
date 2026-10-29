"""Black bar crop detection engine using FFmpeg cropdetect filter."""
import re
import subprocess

from core.config_manager import get_binary_path


def detect_black_bars(video_path: str, sample_time_sec: float = 60.0) -> tuple[str, str, str]:
    """
    Runs FFmpeg cropdetect filter across 60 frames.
    Returns: (crop_filter_str, aspect_ratio_str, full_log)
    """
    ffmpeg_bin = get_binary_path("ffmpeg")

    cmd = [
        ffmpeg_bin, "-y",
        "-ss", str(sample_time_sec),
        "-i", video_path,
        "-vframes", "60",
        "-vf", "cropdetect=24:16:0",
        "-f", "null", "-"
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        crop_pattern = re.compile(r"crop=(\d+:\d+:\d+:\d+)")
        matches = crop_pattern.findall(res.stdout)

        if not matches:
            return "", "Unable to detect crop (no black bars found or scan failed)", res.stdout

        # Pick the most frequently detected crop setting
        from collections import Counter
        counts = Counter(matches)
        best_crop = counts.most_common(1)[0][0]
        w, h, x, y = [int(v) for v in best_crop.split(":")]

        # Compute aspect ratio
        ratio = w / h if h > 0 else 0
        if 2.30 <= ratio <= 2.45:
            aspect_name = f"{ratio:.2f}:1 (Cinematic Anamorphic Scope)"
        elif 1.70 <= ratio <= 1.85:
            aspect_name = f"{ratio:.2f}:1 (16:9 Standard Widescreen)"
        elif 1.30 <= ratio <= 1.38:
            aspect_name = f"{ratio:.2f}:1 (4:3 Classic TV)"
        else:
            aspect_name = f"{ratio:.2f}:1"

        return f"-vf crop={best_crop}", aspect_name, res.stdout
    except Exception as e:
        return "", str(e), str(e)
