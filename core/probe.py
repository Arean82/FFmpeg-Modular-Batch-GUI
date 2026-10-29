"""FFprobe metadata extractor."""
import json
import subprocess
from typing import Any

from core.config_manager import get_binary_path


def probe_file(file_path: str) -> dict[str, Any] | None:
    """Runs ffprobe on a file and returns parsed audio/video metadata."""
    ffprobe_bin = get_binary_path("ffprobe")
    cmd = [
        ffprobe_bin,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)

        info = {
            "format": data.get("format", {}).get("format_name", ""),
            "duration": float(data.get("format", {}).get("duration", 0.0)),
            "size": int(data.get("format", {}).get("size", 0)),
            "video_codec": "N/A",
            "audio_codec": "N/A",
            "resolution": "N/A",
            "bitrate": int(data.get("format", {}).get("bit_rate", 0)) if data.get("format", {}).get("bit_rate") else 0,
            "framerate": "N/A",
            "audio_channels": "N/A",
            "sample_rate": "N/A"
        }

        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type")
            if codec_type == "video" and info["video_codec"] == "N/A":
                info["video_codec"] = stream.get("codec_name", "unknown")
                width = stream.get("width")
                height = stream.get("height")
                if width and height:
                    info["resolution"] = f"{width}x{height}"
                # framerate
                avg_fps = stream.get("avg_frame_rate", "")
                if avg_fps and "/" in avg_fps:
                    try:
                        num, den = avg_fps.split("/")
                        if float(den) > 0:
                            fps_val = float(num) / float(den)
                            info["framerate"] = f"{fps_val:.2f}".rstrip("0").rstrip(".")
                    except Exception:
                        pass
            elif codec_type == "audio" and info["audio_codec"] == "N/A":
                info["audio_codec"] = stream.get("codec_name", "unknown")
                ch = stream.get("channels")
                if ch is not None:
                    info["audio_channels"] = f"{ch} ch"
                sr = stream.get("sample_rate")
                if sr:
                    info["sample_rate"] = f"{int(sr)//1000} kHz" if int(sr) >= 1000 else f"{sr} Hz"

        return info
    except Exception:
        return None
