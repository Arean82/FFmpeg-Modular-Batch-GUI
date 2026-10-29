"""Presets management for FFmpeg Batch AV Converter.

Integrates with SQLite backend (core/database.py) while preserving presets.json
compatibility and supporting JSON bundle export/import.
"""
import json
import os
from typing import Dict, Any

from core.database import (
    init_db,
    db_get_all_presets,
    db_save_preset,
    db_delete_preset,
)

PRESET_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "presets.json")


def load_presets() -> dict:
    """Loads presets from SQLite database (falling back/migrating from presets.json)."""
    init_db()
    presets = db_get_all_presets()
    if not presets and os.path.exists(PRESET_FILE):
        try:
            with open(PRESET_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for name, item in data.items():
                db_save_preset(
                    name=name,
                    ext=item.get("ext", "mp4"),
                    args=item.get("args", ""),
                    category=item.get("category", "General"),
                    desc=item.get("desc", "")
                )
            presets = db_get_all_presets()
        except Exception:
            pass
    return presets


def save_presets(data: dict) -> bool:
    """Saves presets to SQLite and mirrors to presets.json for portability."""
    try:
        init_db()
        for name, item in data.items():
            db_save_preset(
                name=name,
                ext=item.get("ext", "mp4"),
                args=item.get("args", ""),
                category=item.get("category", "General"),
                desc=item.get("desc", "")
            )
        # Mirror to json file for backup/interop
        with open(PRESET_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving presets: {e}")
        return False


def export_presets_bundle(file_path: str, selected_names: list = None) -> bool:
    """Exports all or selected presets to a shareable JSON bundle."""
    try:
        all_presets = load_presets()
        if selected_names:
            bundle = {k: v for k, v in all_presets.items() if k in selected_names}
        else:
            bundle = all_presets

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2)
        return True
    except Exception as e:
        print(f"Error exporting presets bundle: {e}")
        return False


def import_presets_bundle(file_path: str) -> int:
    """Imports presets from an external JSON bundle into SQLite and presets.json."""
    if not os.path.exists(file_path):
        return 0
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return 0
        count = 0
        for name, item in data.items():
            if isinstance(item, dict) and "args" in item:
                db_save_preset(
                    name=name,
                    ext=item.get("ext", "mp4"),
                    args=item.get("args", ""),
                    category=item.get("category", "Imported"),
                    desc=item.get("desc", "")
                )
                count += 1
        # Sync back to presets.json
        save_presets(load_presets())
        return count
    except Exception as e:
        print(f"Error importing presets bundle: {e}")
        return 0
