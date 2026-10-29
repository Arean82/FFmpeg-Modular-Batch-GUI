"""Presets management for FFmpeg Batch AV Converter.

Handles loading, saving, and querying categorized presets directly from presets.json.
No presets are hardcoded in Python.
"""
import os
import json

PRESET_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "presets.json")


def load_presets() -> dict:
    """Loads presets from the external presets.json file."""
    if not os.path.exists(PRESET_FILE):
        return {}

    try:
        with open(PRESET_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading presets from {PRESET_FILE}: {e}")
        return {}


def save_presets(data: dict) -> bool:
    """Saves presets to the external presets.json file."""
    try:
        with open(PRESET_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving presets to {PRESET_FILE}: {e}")
        return False
