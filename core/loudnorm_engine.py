"""EBU R128 and ITU-R BS.1770 audio loudness normalization engine."""
import json
import re
import subprocess
from typing import Any, Dict, Optional, Tuple

from core.config_manager import get_binary_path


LOUDNORM_PRESETS = {
    "YouTube / Spotify Streaming (-14 LUFS)": {
        "i": -14.0,
        "lra": 11.0,
        "tp": -1.0,
        "desc": "Modern digital web streaming standard (YouTube, Spotify, Tidal)."
    },
    "EBU R128 European Broadcast (-23 LUFS)": {
        "i": -23.0,
        "lra": 7.0,
        "tp": -1.0,
        "desc": "European standard for television and radio broadcast."
    },
    "ATSC A/85 US Television (-24 LUFS)": {
        "i": -24.0,
        "lra": 12.0,
        "tp": -2.0,
        "desc": "United States commercial broadcast standard (CALM Act compliant)."
    },
    "Podcast & Spoken Word (-16 LUFS)": {
        "i": -16.0,
        "lra": 9.0,
        "tp": -1.5,
        "desc": "Optimized for voice clarity, speech, and mobile listening."
    },
    "AES TD1004.1.13-15 (-18 LUFS)": {
        "i": -18.0,
        "lra": 10.0,
        "tp": -1.0,
        "desc": "Audio Engineering Society OTT/Video-on-Demand recommendation."
    }
}


def build_loudnorm_filter(
    target_i: float = -14.0,
    target_lra: float = 11.0,
    target_tp: float = -1.0,
    measured_data: Optional[Dict[str, Any]] = None
) -> str:
    """Builds the FFmpeg -af loudnorm filter string."""
    base = f"loudnorm=I={target_i}:LRA={target_lra}:tp={target_tp}"
    if measured_data:
        m_i = measured_data.get("input_i", "")
        m_tp = measured_data.get("input_tp", "")
        m_lra = measured_data.get("input_lra", "")
        m_thresh = measured_data.get("input_thresh", "")
        offset = measured_data.get("target_offset", "")
        if m_i and m_tp and m_lra and m_thresh:
            base += (
                f":measured_I={m_i}"
                f":measured_tp={m_tp}"
                f":measured_LRA={m_lra}"
                f":measured_thresh={m_thresh}"
            )
            if offset:
                base += f":offset={offset}"
            base += ":linear=true"
    return f"-af {base}"


def analyze_audio_loudness(file_path: str) -> Tuple[bool, Dict[str, Any], str]:
    """Runs Pass 1 loudness measurement on the source file."""
    ffmpeg_bin = get_binary_path("ffmpeg")
    cmd = [
        ffmpeg_bin, "-hide_banner",
        "-i", file_path,
        "-vn", "-sn",
        "-af", "loudnorm=I=-16:LRA=11:tp=-1.5:print_format=json",
        "-f", "null",
        "-"
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out = res.stdout
        # Find JSON object output by loudnorm filter in stderr/stdout
        json_match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            return True, parsed, "Pass 1 analysis succeeded."
        else:
            return False, {}, "Could not parse loudnorm measurement JSON from FFmpeg output."
    except Exception as e:
        return False, {}, str(e)
