"""Database layer for Vagamundo v2."""

from __future__ import annotations
import os
import sqlite3
from pathlib import Path

_here = Path(__file__).resolve()
# Root directory of the repository (parent of backend/ or parent of db/ if standalone)
ROOT = _here.parent.parent.parent if _here.parent.parent.name == "backend" else _here.parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "vagamundo.db"


def get_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Connect to SQLite with WAL mode, foreign keys, and busy timeout enabled."""
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(target_path),
        timeout=10.0,
        isolation_level=None,  # autocommit / manual transactions via BEGIN/COMMIT
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

