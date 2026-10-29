"""FFprobe metadata extractor."""
import json
import subprocess
from typing import Dict, Any, Optional
from core.config_manager import get_binary_path

def probe_file(file_path: str) -> Optional[Dict[str, Any]]:
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
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        
        info = {
            "format": data.get("format", {}).get("format_name", ""),
            "duration": float(data.get("format", {}).get("duration", 0.0)),
            "size": int(data.get("format", {}).get("size", 0)),
            "video_codec": "N/A",
            "audio_codec": "N/A",
            "resolution": "N/A",
            "bitrate": int(data.get("format", {}).get("bit_rate", 0)) if data.get("format", {}).get("bit_rate") else 0
        }
        
        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type")
            if codec_type == "video" and info["video_codec"] == "N/A":
                info["video_codec"] = stream.get("codec_name", "unknown")
                width = stream.get("width")
                height = stream.get("height")
                if width and height:
                    info["resolution"] = f"{width}x{height}"
            elif codec_type == "audio" and info["audio_codec"] == "N/A":
                info["audio_codec"] = stream.get("codec_name", "unknown")
                
        return info
    except Exception:
        return None
