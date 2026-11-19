"""Shared SQLite serialization and row-mapping helpers for repository modules."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


def now_iso() -> str:
    """Return current UTC timestamp formatted as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def serialize(val: Any) -> Optional[str]:
    """Serialize structured Python values into JSON text for SQLite columns."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def deserialize(val: Any) -> Any:
    """Deserialize JSON-encoded SQLite strings back into dicts or lists when valid."""
    if val is None:
        return None
    if isinstance(val, str) and (val.startswith("{") or val.startswith("[")):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def row_to_dict(row: sqlite3.Row | None, json_fields: tuple[str, ...] = ()) -> dict | None:
    """Convert a SQLite row into a dictionary, decoding specified JSON fields."""
    if row is None:
        return None
    data = dict(row)
    for field in json_fields:
        if field in data and data[field] is not None:
            data[field] = deserialize(data[field])
    return data
