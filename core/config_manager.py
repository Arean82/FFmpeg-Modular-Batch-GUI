"""Central configuration manager for FFmpeg Batch AV Converter.

Stores binary paths (system vs custom bleeding-edge) and general preferences.
"""
import json
import os
import shutil

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

DEFAULT_CONFIG = {
    "ffmpeg_custom": False,
    "ffmpeg_path": shutil.which("ffmpeg") or "/usr/bin/ffmpeg",
    "ffprobe_custom": False,
    "ffprobe_path": shutil.which("ffprobe") or "/usr/bin/ffprobe",
    "ytdlp_custom": False,
    "ytdlp_path": shutil.which("yt-dlp") or "/usr/bin/yt-dlp",
    "exclusions_enabled": True,
    "exclusions_list": ["txt", "nfo", "srt", "ass", "vtt", "jpg", "png", "ini", "pdf", "url", "part", "zip", "rar", "7z", "torrent", "exe"],
    "auto_scroll_logs": True,
    "play_notification_sound": True,
    "show_desktop_notification": True,
    "hw_accel": "Auto (VAAPI / NVENC / QSV)",
    "process_priority": "Normal",
    "pause_on_battery": False,
    "output_naming_pattern": "%~n_converted",
    "overwrite_mode": "overwrite",
    "on_finish_action": "none",
    "run_script_enabled": False,
    "run_script_path": "",
    "theme_engine": "qss",
    "theme_mode": "system",
    "material_theme": "default"
}

def get_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception:
            pass
    return config

def save_config(config: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")

def get_binary_path(name: str) -> str:
    """Returns the effective binary path (custom if enabled and valid, else system)."""
    cfg = get_config()
    if name == "ffmpeg":
        if cfg.get("ffmpeg_custom") and cfg.get("ffmpeg_path"):
            return cfg["ffmpeg_path"]
        return shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    elif name == "ffprobe":
        if cfg.get("ffprobe_custom") and cfg.get("ffprobe_path"):
            return cfg["ffprobe_path"]
        return shutil.which("ffprobe") or "/usr/bin/ffprobe"
    elif name == "yt-dlp":
        if cfg.get("ytdlp_custom") and cfg.get("ytdlp_path"):
            return cfg["ytdlp_path"]
        return shutil.which("yt-dlp") or "/usr/bin/yt-dlp"
    return name
