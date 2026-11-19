"""Idempotent SQLite schema migrations and historical backfill helpers."""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)


def _add_missing_columns(
    conn: sqlite3.Connection,
    table: str,
    columns: dict[str, str],
    indexes: tuple[str, ...] = (),
) -> None:
    """Add missing columns and optional indexes to an existing SQLite table idempotently."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cur.fetchall()}
    if not existing:
        return
    with conn:
        for col, ddl in columns.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        for idx_sql in indexes:
            conn.execute(idx_sql)


def _migrate_recruiter_posts(conn: sqlite3.Connection) -> None:
    try:
        _add_missing_columns(
            conn,
            "recruiter_posts",
            {
                "ai_classification": "TEXT",
                "ai_score": "INTEGER",
                "ai_verdict": "TEXT",
                "ai_summary": "TEXT",
                "ai_best_email": "TEXT",
                "ai_model": "TEXT",
                "ai_details": "TEXT",
                "ai_evaluated_at": "TEXT",
                "auto_promoted": "INTEGER DEFAULT 0",
                "auto_run_id": "TEXT",
                "contacted_email": "TEXT",
                "contacted_at": "TEXT",
            },
            indexes=(
                "CREATE INDEX IF NOT EXISTS idx_recruiter_posts_ai_class ON recruiter_posts(ai_classification)",
                "CREATE INDEX IF NOT EXISTS idx_recruiter_posts_auto_run ON recruiter_posts(auto_run_id)",
            ),
        )
    except sqlite3.Error as exc:
        logger.warning("Failed to migrate recruiter_posts columns: %s", exc)


def _migrate_applications(conn: sqlite3.Connection) -> None:
    try:
        _add_missing_columns(
            conn,
            "applications",
            {
                "contact_channel": "TEXT DEFAULT 'portal'",
                "contacted_email": "TEXT",
                "recruiter_post_id": "INTEGER",
            },
            indexes=(
                "CREATE INDEX IF NOT EXISTS idx_applications_contacted_email ON applications(contacted_email)",
            ),
        )
    except sqlite3.Error as exc:
        logger.warning("Failed to migrate applications columns: %s", exc)


def _migrate_evaluations(conn: sqlite3.Connection) -> None:
    try:
        _add_missing_columns(
            conn,
            "evaluations",
            {
                "language_gate": "TEXT",
                "language_note": "TEXT",
            },
        )
    except sqlite3.Error as exc:
        logger.warning("Failed to migrate evaluations columns: %s", exc)


def _backfill_ledger(conn: sqlite3.Connection) -> None:
    """Ensure all current and historical applied jobs exist in application_ledger."""
    try:
        with conn:
            conn.execute("""
                INSERT INTO application_ledger (job_id, company, role, portal, job_url, applied_date, applied_at, active_in_list)
                SELECT
                    a.job_id,
                    COALESCE(j.company, 'Empresa'),
                    COALESCE(j.title, 'Cargo'),
                    COALESCE(j.portal, 'portal'),
                    COALESCE(j.url, ''),
                    COALESCE(a.applied_date, substr(a.created_at, 1, 10)),
                    a.created_at,
                    1
                FROM applications a
                LEFT JOIN jobs j ON a.job_id = j.id
                WHERE j.id IS NOT NULL
                  AND j.company IS NOT NULL AND TRIM(j.company) != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM application_ledger l
                    WHERE (l.job_id IS NOT NULL AND l.job_id = a.job_id)
                       OR (l.company = j.company AND l.role = j.title AND l.applied_date = COALESCE(a.applied_date, substr(a.created_at, 1, 10)))
                  )
            """)

            conn.execute("""
                INSERT INTO application_ledger (job_id, company, role, portal, job_url, applied_date, applied_at, active_in_list, archived_at)
                SELECT
                    sl.job_id,
                    COALESCE(j.company, 'Empresa'),
                    COALESCE(j.title, 'Cargo'),
                    COALESCE(j.portal, 'portal'),
                    COALESCE(j.url, ''),
                    substr(sl.created_at, 1, 10),
                    sl.created_at,
                    CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END,
                    CASE WHEN a.id IS NULL THEN sl.created_at ELSE NULL END
                FROM status_log sl
                LEFT JOIN jobs j ON sl.job_id = j.id
                LEFT JOIN applications a ON sl.job_id = a.job_id
                WHERE sl.to_status = 'applied'
                  AND j.id IS NOT NULL
                  AND j.company IS NOT NULL AND TRIM(j.company) != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM application_ledger l
                    WHERE (l.job_id IS NOT NULL AND l.job_id = sl.job_id)
                       OR (l.company = j.company AND l.role = j.title AND l.applied_date = substr(sl.created_at, 1, 10))
                  )
            """)
    except sqlite3.Error as exc:
        logger.warning("Failed to backfill application_ledger: %s", exc)


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Run all idempotent schema upgrades and ledger backfills on an open connection."""
    _migrate_recruiter_posts(conn)
    _migrate_applications(conn)
    _migrate_evaluations(conn)
    _backfill_ledger(conn)
