"""Unified Repository facade composing domain SQLite mixins with thread-safe connections."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from backend.db import ROOT, RepositoryError, get_db  # noqa: F401 - re-exported for legacy callers
from backend.db.analytics_repo import AnalyticsRepositoryMixin
from backend.db.applications_repo import ApplicationsRepositoryMixin
from backend.db.jobs_repo import JobsRepositoryMixin
from backend.db.migrations import apply_migrations
from backend.db.recruiters_repo import RecruitersRepositoryMixin
from backend.db.utils import deserialize as _deserialize  # noqa: F401
from backend.db.utils import now_iso as _now_iso  # noqa: F401
from backend.db.utils import row_to_dict
from backend.db.utils import serialize as _serialize  # noqa: F401

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
logger = logging.getLogger(__name__)


class Repository(
    JobsRepositoryMixin,
    ApplicationsRepositoryMixin,
    RecruitersRepositoryMixin,
    AnalyticsRepositoryMixin,
):
    """Manages SQLite connections and composes all domain persistence operations."""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = db_path
        self._is_memory = str(db_path or "") == ":memory:" or "mode=memory" in str(db_path or "")
        self._main_thread_id = threading.get_ident()
        self._local = threading.local()
        self._thread_conns: dict[int, sqlite3.Connection] = {}
        self._conn_lock = threading.Lock()
        self._main_conn = get_db(db_path)
        self._init_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        tid = threading.get_ident()
        if self._is_memory or tid == self._main_thread_id:
            return self._main_conn
        c = getattr(self._local, "conn", None)
        if c is None:
            c = get_db(self._db_path)
            self._local.conn = c
            with self._conn_lock:
                alive = {t.ident for t in threading.enumerate() if t.ident is not None}
                for old_tid in list(self._thread_conns.keys()):
                    if old_tid not in alive:
                        old_conn = self._thread_conns.pop(old_tid, None)
                        if old_conn is not None:
                            try:
                                old_conn.close()
                            except sqlite3.Error as exc:
                                logger.debug("Failed to close stale thread DB connection: %s", exc)
                self._thread_conns[tid] = c
        return c

    @conn.setter
    def conn(self, value: sqlite3.Connection) -> None:
        self._main_conn = value

    def _init_schema(self) -> None:
        if SCHEMA_PATH.exists():
            schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
            self.conn.executescript(schema_sql)
        apply_migrations(self.conn)

    def close(self) -> None:
        with self._conn_lock:
            conns = list(self._thread_conns.values())
            self._thread_conns.clear()
        for c in conns:
            try:
                c.close()
            except sqlite3.Error as exc:
                logger.debug("Failed to close worker DB connection: %s", exc)
        if getattr(self, "_main_conn", None):
            try:
                self._main_conn.close()
            except sqlite3.Error as exc:
                logger.debug("Failed to close main DB connection: %s", exc)

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _row_to_dict(self, row: sqlite3.Row | None, json_fields: tuple = ()) -> dict | None:
        return row_to_dict(row, json_fields)
