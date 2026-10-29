"""SQLite database management layer for FFmpeg Modular Batch GUI.

Handles:
- Queue crash-recovery persistence
- Historical job audit logs (inputs, outputs, durations, error traces)
- User presets storage with export/import capabilities
"""

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional


DB_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffbatch.db")


def get_db_connection() -> sqlite3.Connection:
    """Creates or opens the local SQLite database connection."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes tables and performs automated migrations."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Active Queue Table (Crash Recovery)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'Pending',
                meta_json TEXT,
                output_path TEXT,
                position INTEGER DEFAULT 0
            )
        """)

        # 2. Historical Job Audit Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                output_path TEXT,
                params TEXT,
                success INTEGER NOT NULL,
                error_msg TEXT,
                duration_sec REAL DEFAULT 0,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Presets Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS presets (
                name TEXT PRIMARY KEY,
                category TEXT DEFAULT 'Custom',
                ext TEXT DEFAULT 'mp4',
                args TEXT NOT NULL,
                desc TEXT DEFAULT ''
            )
        """)
        conn.commit()

    # Migrate legacy files if needed
    _migrate_legacy_files()


def _migrate_legacy_files():
    """Migrates existing presets.json into SQLite if presets table is empty."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    presets_json_path = os.path.join(base_dir, "presets.json")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM presets")
        if cursor.fetchone()["cnt"] == 0 and os.path.exists(presets_json_path):
            try:
                with open(presets_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for name, item in data.items():
                    cursor.execute("""
                        INSERT OR REPLACE INTO presets (name, category, ext, args, desc)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        name,
                        item.get("category", "General"),
                        item.get("ext", "mp4"),
                        item.get("args", ""),
                        item.get("desc", "")
                    ))
                conn.commit()
            except Exception:
                pass


# --- Queue Persistence Functions ---

def db_save_queue(items: List[Dict[str, Any]]):
    """Saves the current queue snapshot into SQLite."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM queue_state")
        for idx, it in enumerate(items):
            p = it.get("path")
            if not p:
                continue
            status = it.get("status", "Pending")
            meta = json.dumps(it.get("meta", {}))
            out_p = it.get("output_path", "")
            cursor.execute("""
                INSERT INTO queue_state (file_path, status, meta_json, output_path, position)
                VALUES (?, ?, ?, ?, ?)
            """, (p, status, meta, out_p, idx))
        conn.commit()


def db_load_queue() -> List[Dict[str, Any]]:
    """Loads pending queue snapshot from SQLite."""
    items = []
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path, status, meta_json, output_path FROM queue_state ORDER BY position ASC")
        for row in cursor.fetchall():
            meta = {}
            if row["meta_json"]:
                try:
                    meta = json.loads(row["meta_json"])
                except Exception:
                    pass
            items.append({
                "path": row["file_path"],
                "status": row["status"],
                "meta": meta,
                "output_path": row["output_path"]
            })
    return items


def db_clear_queue():
    """Clears saved queue state."""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM queue_state")
        conn.commit()


# --- Job History & Failure Logging Functions ---

def db_log_job_history(file_path: str, output_path: str, params: str, success: bool, error_msg: str, duration_sec: float = 0.0):
    """Records an audit log entry for a completed or failed encoding job."""
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO job_history (file_path, output_path, params, success, error_msg, duration_sec)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (file_path, output_path, params, 1 if success else 0, error_msg, duration_sec))
        conn.commit()


def db_get_last_error(file_path: str) -> Optional[Dict[str, Any]]:
    """Retrieves the latest failure trace and params for a specific file."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT file_path, output_path, params, error_msg, completed_at
            FROM job_history
            WHERE file_path = ? AND success = 0
            ORDER BY id DESC LIMIT 1
        """, (file_path,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


# --- Presets Functions ---

def db_get_all_presets() -> Dict[str, Dict[str, Any]]:
    """Retrieves all presets as a dictionary matching legacy format."""
    res = {}
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, category, ext, args, desc FROM presets ORDER BY name ASC")
        for r in cursor.fetchall():
            res[r["name"]] = {
                "category": r["category"],
                "ext": r["ext"],
                "args": r["args"],
                "desc": r["desc"]
            }
    return res


def db_save_preset(name: str, ext: str, args: str, category: str = "Custom", desc: str = ""):
    """Inserts or updates a preset in SQLite."""
    with get_db_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO presets (name, category, ext, args, desc)
            VALUES (?, ?, ?, ?, ?)
        """, (name, category, ext, args, desc))
        conn.commit()


def db_delete_preset(name: str):
    """Deletes a preset by name."""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM presets WHERE name = ?", (name,))
        conn.commit()
