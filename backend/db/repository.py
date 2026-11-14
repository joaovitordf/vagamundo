"""Data Access Layer (Repository) for Vagamundo v2."""

from __future__ import annotations
import hashlib
import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Any, Optional

from backend.db import get_db, ROOT

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def _deserialize(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, str) and (val.startswith("{") or val.startswith("[")):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


class Repository:
    """Manages SQLite queries, transactions, and object mapping."""

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
        self._migrate_recruiter_posts()
        self._migrate_applications()
        self._migrate_evaluations()
        self._backfill_ledger()

    def _migrate_recruiter_posts(self) -> None:
        """Idempotently add AI triage, auto-mode & outreach columns to existing recruiter_posts tables."""
        try:
            cur = self.conn.execute("PRAGMA table_info(recruiter_posts)")
            existing = {r["name"] for r in cur.fetchall()}
            if not existing:
                return
            columns = {
                "ai_classification": "TEXT",
                "ai_score": "INTEGER",
                "ai_verdict": "TEXT",
                "ai_summary": "TEXT",
                "ai_best_email": "TEXT",
                "ai_model": "TEXT",
                "ai_evaluated_at": "TEXT",
                "auto_promoted": "INTEGER DEFAULT 0",
                "auto_run_id": "TEXT",
                "contacted_email": "TEXT",
                "contacted_at": "TEXT",
            }
            with self.conn:
                for col, ddl in columns.items():
                    if col not in existing:
                        self.conn.execute(f"ALTER TABLE recruiter_posts ADD COLUMN {col} {ddl}")
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_recruiter_posts_ai_class ON recruiter_posts(ai_classification)"
                )
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_recruiter_posts_auto_run ON recruiter_posts(auto_run_id)"
                )
        except sqlite3.Error as exc:
            logger.warning("Failed to migrate recruiter_posts columns: %s", exc)

    def _migrate_applications(self) -> None:
        """Idempotently add direct recruiter outreach tracking columns to existing applications tables."""
        try:
            cur = self.conn.execute("PRAGMA table_info(applications)")
            existing = {r["name"] for r in cur.fetchall()}
            if not existing:
                return
            columns = {
                "contact_channel": "TEXT DEFAULT 'portal'",
                "contacted_email": "TEXT",
                "recruiter_post_id": "INTEGER",
            }
            with self.conn:
                for col, ddl in columns.items():
                    if col not in existing:
                        self.conn.execute(f"ALTER TABLE applications ADD COLUMN {col} {ddl}")
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_applications_contacted_email ON applications(contacted_email)"
                )
        except sqlite3.Error as exc:
            logger.warning("Failed to migrate applications columns: %s", exc)

    def _migrate_evaluations(self) -> None:
        """Idempotently add language gate columns to existing evaluations tables."""
        try:
            cur = self.conn.execute("PRAGMA table_info(evaluations)")
            existing = {r["name"] for r in cur.fetchall()}
            if not existing:
                return
            columns = {
                "language_gate": "TEXT",
                "language_note": "TEXT",
            }
            with self.conn:
                for col, ddl in columns.items():
                    if col not in existing:
                        self.conn.execute(f"ALTER TABLE evaluations ADD COLUMN {col} {ddl}")
        except sqlite3.Error as exc:
            logger.warning("Failed to migrate evaluations columns: %s", exc)

    def _backfill_ledger(self) -> None:
        """Ensure all current and historic applied jobs are recorded in application_ledger."""
        try:
            with self.conn:
                # 1. Backfill from applications table
                self.conn.execute("""
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

                # 2. Backfill from status_log for past applications
                self.conn.execute("""
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
        if row is None:
            return None
        d = dict(row)
        for field in json_fields:
            if field in d and d[field] is not None:
                d[field] = _deserialize(d[field])
        return d

    # -------------------------------------------------------------------------
    # Jobs CRUD
    # -------------------------------------------------------------------------

    JOB_JSON_FIELDS = ("strengths", "gaps", "signals", "also_on", "full_posting")

    def upsert_job(self, job: dict) -> str:
        """Insert or update a job posting in the database."""
        job_id = job.get("id")
        title = job.get("title", "")
        company = job.get("company", "")
        url = job.get("url", "")

        # Generate canonical slug key if id is missing or purely numeric portal ID
        if not job_id or (isinstance(job_id, str) and job_id.isdigit()):
            try:
                from backend.tools.job_key import make_key
                job_id = make_key(company, title, url)
            except (ImportError, ValueError, TypeError):
                seed = (url or f"{company}|{title}").encode("utf-8", errors="ignore")
                job_id = f"job-{hashlib.sha256(seed).hexdigest()[:12]}"

        now = _now_iso()
        work_model = job.get("work_model") or job.get("workplace_type")
        contract_type = job.get("contract_type") or job.get("contract")
        posted_date = job.get("posted_date") or job.get("date")

        with self.conn:
            # Check existing by id or url atomically inside the write transaction
            cur = self.conn.execute(
                "SELECT id, created_at, status, fit, rank_score, rank_verdict FROM jobs WHERE id = ? OR (? != '' AND url = ?)",
                (job_id, url, url),
            )
            row = cur.fetchone()

            status = job.get("status") or (row["status"] if row else "new")
            fit = job.get("fit") or (row["fit"] if row else None)

            # Normalize score and verdict from screening dict if present
            rank_score = job.get("rank_score")
            rank_verdict = job.get("rank_verdict")
            screening = job.get("screening")
            if isinstance(screening, dict):
                if rank_score is None:
                    rank_score = screening.get("score")
                if rank_verdict is None:
                    rank_verdict = screening.get("verdict")
            if row:
                if rank_score is None:
                    rank_score = row["rank_score"]
                if rank_verdict is None:
                    rank_verdict = row["rank_verdict"]

            if row:
                target_id = row["id"]
                self.conn.execute(
                    """
                    UPDATE jobs SET
                        title = COALESCE(?, title),
                        company = COALESCE(?, company),
                        url = COALESCE(?, url),
                        location = COALESCE(?, location),
                        portal = COALESCE(?, portal),
                        source = COALESCE(?, source),
                        work_model = COALESCE(?, work_model),
                        contract_type = COALESCE(?, contract_type),
                        seniority = COALESCE(?, seniority),
                        description = COALESCE(?, description),
                        posted_date = COALESCE(?, posted_date),
                        deadline = COALESCE(?, deadline),
                        first_seen = COALESCE(?, first_seen),
                        status = ?,
                        fit = ?,
                        rank_score = COALESCE(?, rank_score),
                        rank_verdict = COALESCE(?, rank_verdict),
                        rank_date = COALESCE(?, rank_date),
                        location_verdict = COALESCE(?, location_verdict),
                        language_gate = COALESCE(?, language_gate),
                        language_note = COALESCE(?, language_note),
                        strengths = COALESCE(?, strengths),
                        gaps = COALESCE(?, gaps),
                        signals = COALESCE(?, signals),
                        also_on = COALESCE(?, also_on),
                        full_posting = COALESCE(?, full_posting),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        job.get("title"),
                        job.get("company"),
                        job.get("url"),
                        job.get("location"),
                        job.get("portal"),
                        job.get("source"),
                        work_model,
                        contract_type,
                        job.get("seniority"),
                        job.get("description"),
                        posted_date,
                        job.get("deadline"),
                        job.get("first_seen"),
                        status,
                        fit,
                        rank_score,
                        rank_verdict,
                        job.get("rank_date"),
                        job.get("location_verdict"),
                        job.get("language_gate"),
                        job.get("language_note"),
                        _serialize(job.get("strengths")),
                        _serialize(job.get("gaps")),
                        _serialize(job.get("signals")),
                        _serialize(job.get("also_on")),
                        _serialize(job.get("full_posting")),
                        now,
                        target_id,
                    ),
                )
                return target_id
            else:
                self.conn.execute(
                    """
                    INSERT INTO jobs (
                        id, title, company, url, location, portal, source,
                        work_model, contract_type, seniority, description,
                        posted_date, deadline, first_seen, status, fit,
                        rank_score, rank_verdict, rank_date, location_verdict,
                        language_gate, language_note, strengths, gaps, signals,
                        also_on, full_posting, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    )
                    """,
                    (
                        job_id,
                        title,
                        company,
                        url,
                        job.get("location"),
                        job.get("portal"),
                        job.get("source", "cli"),
                        work_model,
                        contract_type,
                        job.get("seniority"),
                        job.get("description"),
                        posted_date,
                        job.get("deadline"),
                        job.get("first_seen", now[:10]),
                        status,
                        fit,
                        rank_score,
                        rank_verdict,
                        job.get("rank_date"),
                        job.get("location_verdict"),
                        job.get("language_gate"),
                        job.get("language_note"),
                        _serialize(job.get("strengths")),
                        _serialize(job.get("gaps")),
                        _serialize(job.get("signals")),
                        _serialize(job.get("also_on")),
                        _serialize(job.get("full_posting")),
                        now,
                        now,
                    ),
                )
                return job_id

    def get_job(self, job_id: str) -> dict | None:
        """Fetch a job by its canonical ID."""
        cur = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return self._row_to_dict(cur.fetchone(), self.JOB_JSON_FIELDS)

    def get_job_by_url(self, url: str) -> dict | None:
        """Fetch a job by its URL."""
        cur = self.conn.execute("SELECT * FROM jobs WHERE url = ?", (url,))
        return self._row_to_dict(cur.fetchone(), self.JOB_JSON_FIELDS)

    def get_job_by_company_title(self, company: str, title: str) -> dict | None:
        """Fetch a job matching normalized (company, title)."""
        if not (company and title):
            return None
        cur = self.conn.execute(
            """
            SELECT * FROM jobs
            WHERE LOWER(TRIM(company)) = LOWER(TRIM(?))
              AND LOWER(TRIM(title)) = LOWER(TRIM(?))
            ORDER BY updated_at DESC LIMIT 1
            """,
            (company, title),
        )
        return self._row_to_dict(cur.fetchone(), self.JOB_JSON_FIELDS)

    def get_applied_index_rows(self) -> list[dict]:
        """Return URL and (company, title) rows of already-applied jobs across ledger and jobs."""
        rows: list[dict] = []
        queries = (
            "SELECT job_url AS url, company, role AS title FROM application_ledger",
            "SELECT url, company, title FROM jobs WHERE status = 'applied'",
        )
        for sql in queries:
            try:
                cur = self.conn.execute(sql)
                rows.extend(dict(r) for r in cur.fetchall())
            except sqlite3.Error as exc:
                logger.warning("Failed to query applied index: %s", exc)
        return rows

    def update_job_ranking(
        self,
        job_id: str,
        score: float | None,
        verdict: str | None,
        details: dict | None = None,
    ) -> None:
        """Persist quick triage / ranking metadata onto jobs without creating a full evaluation."""
        det = details if isinstance(details, dict) else {}
        with self.conn:
            self.conn.execute(
                """
                UPDATE jobs SET
                    rank_score = COALESCE(?, rank_score),
                    rank_verdict = COALESCE(?, rank_verdict),
                    rank_date = ?,
                    location_verdict = COALESCE(?, location_verdict),
                    language_gate = COALESCE(?, language_gate),
                    language_note = COALESCE(?, language_note),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    int(score) if score is not None else None,
                    verdict,
                    date.today().isoformat(),
                    det.get("location_verdict"),
                    det.get("language_gate"),
                    det.get("language_note"),
                    _now_iso(),
                    job_id,
                ),
            )

    @staticmethod
    def _build_jobs_where(
        status: str | None = None,
        fit: str | None = None,
        portal: str | None = None,
        q: str | None = None,
    ) -> tuple[str, list[Any]]:
        where = " WHERE 1=1"
        params: list[Any] = []
        if status:
            where += " AND status = ?"
            params.append(status)
        if fit:
            where += " AND fit = ?"
            params.append(fit)
        if portal:
            where += " AND portal = ?"
            params.append(portal)
        if q:
            where += " AND (title LIKE ? OR company LIKE ? OR description LIKE ?)"
            term = f"%{q}%"
            params.extend([term, term, term])
        return where, params

    def list_jobs(
        self,
        status: str | None = None,
        fit: str | None = None,
        portal: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """List jobs matching the specified filters."""
        where, params = self._build_jobs_where(status=status, fit=fit, portal=portal, q=q)
        query = f"SELECT * FROM jobs{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur = self.conn.execute(query, params)
        return [self._row_to_dict(row, self.JOB_JSON_FIELDS) for row in cur.fetchall()]

    def count_jobs(
        self,
        status: str | None = None,
        fit: str | None = None,
        portal: str | None = None,
        q: str | None = None,
    ) -> int:
        """Count jobs matching the specified filters."""
        where, params = self._build_jobs_where(status=status, fit=fit, portal=portal, q=q)
        cur = self.conn.execute(f"SELECT COUNT(*) as cnt FROM jobs{where}", params)
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def mark_jobs(
        self,
        ids: list[str],
        decision: str,
        source: str = "cli",
        note: str = "",
    ) -> int:
        """Update status/fit of multiple jobs and record audit history in status_log."""
        if not ids:
            return 0

        # Standardize decisions
        fit_val = None
        new_status = decision
        if decision in ("interested", "me-interessa", "interesse", "medium"):
            new_status = "interested"
            fit_val = "medium"
        elif decision in ("discarded", "descartar", "low", "skipped"):
            new_status = "discarded"
            fit_val = "low"
        elif decision in ("high", "top"):
            fit_val = "high"

        now = _now_iso()
        updated_count = 0

        with self.conn:
            for jid in ids:
                cur = self.conn.execute("SELECT status, fit FROM jobs WHERE id = ?", (jid,))
                row = cur.fetchone()
                if not row:
                    continue

                old_status = row["status"]
                target_fit = fit_val if fit_val is not None else row["fit"]

                self.conn.execute(
                    "UPDATE jobs SET status = ?, fit = ?, updated_at = ? WHERE id = ?",
                    (new_status, target_fit, now, jid),
                )
                self.conn.execute(
                    """
                    INSERT INTO status_log (job_id, from_status, to_status, source, note, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (jid, old_status, new_status, source, note, now),
                )
                updated_count += 1

        return updated_count

    # -------------------------------------------------------------------------
    # Evaluations CRUD
    # -------------------------------------------------------------------------

    EVAL_JSON_FIELDS = ("strengths", "gaps")

    def insert_evaluation(self, eval_data: dict) -> int:
        """Insert an AI evaluation score report."""
        now = _now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO evaluations (
                    job_id, score_technical, score_experience, score_behavioral,
                    score_location, score_career, score_global, verdict,
                    strengths, gaps, language_gate, language_note,
                    report_md, ai_provider, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval_data.get("job_id"),
                    eval_data.get("score_technical"),
                    eval_data.get("score_experience"),
                    eval_data.get("score_behavioral"),
                    eval_data.get("score_location"),
                    eval_data.get("score_career"),
                    eval_data.get("score_global"),
                    eval_data.get("verdict"),
                    _serialize(eval_data.get("strengths")),
                    _serialize(eval_data.get("gaps")),
                    eval_data.get("language_gate"),
                    eval_data.get("language_note"),
                    eval_data.get("report_md"),
                    eval_data.get("ai_provider"),
                    now,
                ),
            )
            eval_id = cur.lastrowid

            # Also update job record with evaluation summary
            job_id = eval_data.get("job_id")
            if job_id:
                self.conn.execute(
                    """
                    UPDATE jobs SET
                        rank_score = ?,
                        rank_verdict = ?,
                        rank_date = ?,
                        location_verdict = COALESCE(?, location_verdict),
                        language_gate = COALESCE(?, language_gate),
                        language_note = COALESCE(?, language_note),
                        strengths = COALESCE(?, strengths),
                        gaps = COALESCE(?, gaps),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        eval_data.get("score_global"),
                        eval_data.get("verdict"),
                        now[:10],
                        eval_data.get("score_location"),
                        eval_data.get("language_gate"),
                        eval_data.get("language_note"),
                        _serialize(eval_data.get("strengths")) if eval_data.get("strengths") else None,
                        _serialize(eval_data.get("gaps")) if eval_data.get("gaps") else None,
                        now,
                        job_id,
                    ),
                )

            return eval_id

    def get_evaluation(self, job_id: str) -> dict | None:
        """Get the most recent evaluation for a job."""
        cur = self.conn.execute(
            "SELECT * FROM evaluations WHERE job_id = ? ORDER BY id DESC LIMIT 1",
            (job_id,),
        )
        return self._row_to_dict(cur.fetchone(), self.EVAL_JSON_FIELDS)

    # -------------------------------------------------------------------------
    # Applications CRUD
    # -------------------------------------------------------------------------

    def upsert_application(self, app: dict) -> int:
        """Insert or update an application tracker row."""
        app_id = app.get("id")
        job_id = app.get("job_id")
        now = _now_iso()

        with self.conn:
            # If app_id is not given, check if an application with this job_id already exists to prevent duplicates
            if not app_id and job_id:
                cur = self.conn.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,))
                existing = cur.fetchone()
                if existing:
                    app_id = existing["id"]

            if app_id:
                self.conn.execute(
                    """
                    UPDATE applications SET
                        status = COALESCE(?, status),
                        cv_path = COALESCE(?, cv_path),
                        cover_letter_path = COALESCE(?, cover_letter_path),
                        interview_notes_path = COALESCE(?, interview_notes_path),
                        applied_date = COALESCE(?, applied_date),
                        notes = COALESCE(?, notes),
                        contact_channel = COALESCE(?, contact_channel),
                        contacted_email = COALESCE(?, contacted_email),
                        recruiter_post_id = COALESCE(?, recruiter_post_id),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        app.get("status"),
                        app.get("cv_path"),
                        app.get("cover_letter_path"),
                        app.get("interview_notes_path"),
                        app.get("applied_date"),
                        app.get("notes"),
                        app.get("contact_channel"),
                        app.get("contacted_email"),
                        app.get("recruiter_post_id"),
                        now,
                        app_id,
                    ),
                )
                return app_id
            else:
                cur = self.conn.execute(
                    """
                    INSERT INTO applications (
                        job_id, status, cv_path, cover_letter_path,
                        interview_notes_path, applied_date, notes,
                        contact_channel, contacted_email, recruiter_post_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        app.get("status", "applied"),
                        app.get("cv_path"),
                        app.get("cover_letter_path"),
                        app.get("interview_notes_path"),
                        app.get("applied_date", now[:10]),
                        app.get("notes"),
                        app.get("contact_channel") or "portal",
                        app.get("contacted_email"),
                        app.get("recruiter_post_id"),
                        now,
                        now,
                    ),
                )
                return cur.lastrowid

    def delete_application(self, app_id: int | None = None, job_id: str | None = None) -> int:
        """Delete an application by its id or associated job_id."""
        with self.conn:
            if app_id:
                cur = self.conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
                return cur.rowcount
            elif job_id:
                cur = self.conn.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
                return cur.rowcount
            return 0

    def get_application(self, app_id: int) -> dict | None:
        """Fetch application record by id."""
        cur = self.conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_applications(self, status: str | None = None) -> list[dict]:
        """List all applications with joined job metadata and event counts."""
        query = """
            SELECT a.*, j.title as job_title, j.company as job_company, j.url as job_url,
                   j.portal as job_portal, j.location as job_location,
                   j.description as job_description,
                   j.posted_date as job_posted_date, j.created_at as job_created_at,
                   (SELECT COUNT(*) FROM application_events WHERE application_id = a.id) as event_count,
                   (SELECT stage FROM application_events WHERE application_id = a.id ORDER BY event_date DESC, id DESC LIMIT 1) as latest_event_stage
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE 1=1
        """
        params: list[Any] = []
        if status:
            query += " AND a.status = ?"
            params.append(status)
        query += " ORDER BY a.updated_at DESC"

        cur = self.conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    # -------------------------------------------------------------------------
    # Application Events CRUD (Interview Stages, Feedback, Q&A)
    # -------------------------------------------------------------------------

    def insert_application_event(self, event_data: dict) -> int:
        """Insert an interview stage, feedback, or Q&A event."""
        now = _now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO application_events (
                    application_id, stage, event_date, feedback,
                    questions_and_answers, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_data["application_id"],
                    event_data.get("stage") or "Entrevista",
                    event_data.get("event_date") or now[:10],
                    event_data.get("feedback") or "",
                    event_data.get("questions_and_answers") or "",
                    now,
                ),
            )
            event_id = cur.lastrowid

            # Also update applications.updated_at
            self.conn.execute(
                "UPDATE applications SET updated_at = ? WHERE id = ?",
                (now, event_data["application_id"]),
            )
            return event_id

    def list_application_events(self, application_id: int | None = None) -> list[dict]:
        """List all interview stage events, optionally filtered by application_id."""
        query = """
            SELECT e.*, a.job_id, j.title as job_title, j.company as job_company
            FROM application_events e
            JOIN applications a ON e.application_id = a.id
            JOIN jobs j ON a.job_id = j.id
            WHERE 1=1
        """
        params: list[Any] = []
        if application_id is not None:
            query += " AND e.application_id = ?"
            params.append(application_id)
        query += " ORDER BY e.event_date DESC, e.id DESC"

        cur = self.conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def delete_application_event(self, event_id: int) -> int:
        """Delete an interview event by its ID."""
        with self.conn:
            cur = self.conn.execute("DELETE FROM application_events WHERE id = ?", (event_id,))
            return cur.rowcount

    # -------------------------------------------------------------------------
    # Scan Runs
    # -------------------------------------------------------------------------

    SCAN_JSON_FIELDS = ("portals_summary", "health_report")

    def insert_scan_run(self, run: dict) -> int:
        """Record statistics of a scan run."""
        now = _now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO scan_runs (
                    date, total_found, total_new, total_seen,
                    portals_summary, health_report, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.get("date", now[:10]),
                    run.get("total_found", 0),
                    run.get("total_new", 0),
                    run.get("total_seen", 0),
                    _serialize(run.get("portals_summary")),
                    _serialize(run.get("health_report")),
                    now,
                ),
            )
            return cur.lastrowid

    # -------------------------------------------------------------------------
    # Profile & Key-Value settings
    # -------------------------------------------------------------------------

    def get_profile(self, key: str) -> str | None:
        cur = self.conn.execute("SELECT value FROM profile WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def set_profile(self, key: str, value: str) -> None:
        now = _now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO profile (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    # -------------------------------------------------------------------------
    # Application Ledger & Dashboard Analytics
    # -------------------------------------------------------------------------

    def record_application_ledger(
        self,
        company: str,
        role: str,
        portal: str = "",
        job_url: str = "",
        job_id: str | None = None,
        applied_date: str = "",
        applied_at: str = "",
    ) -> int:
        """Record or update an immutable application entry in application_ledger."""
        now = _now_iso()
        applied_date = applied_date or now[:10]
        applied_at = applied_at or now

        # Reject records with missing required fields
        if not (company and company.strip()) or not (role and role.strip()) or not (job_url and job_url.strip()):
            return 0

        with self.conn:
            # Check if matching record exists
            cur = self.conn.execute(
                """
                SELECT id FROM application_ledger
                WHERE (job_id IS NOT NULL AND job_id != '' AND job_id = ?)
                   OR (job_url IS NOT NULL AND job_url != '' AND job_url = ?)
                   OR (LOWER(TRIM(company)) = LOWER(TRIM(?)) AND LOWER(TRIM(role)) = LOWER(TRIM(?)) AND applied_date = ?)
                LIMIT 1
                """,
                (job_id or "", job_url or "", company, role, applied_date),
            )
            row = cur.fetchone()
            if row:
                self.conn.execute(
                    """
                    UPDATE application_ledger
                    SET active_in_list = 1, archived_at = NULL,
                        company = COALESCE(NULLIF(?, ''), company),
                        role = COALESCE(NULLIF(?, ''), role),
                        portal = COALESCE(NULLIF(?, ''), portal)
                    WHERE id = ?
                    """,
                    (company, role, portal, row["id"]),
                )
                return row["id"]
            else:
                cur = self.conn.execute(
                    """
                    INSERT INTO application_ledger (
                        job_id, company, role, portal, job_url, applied_date, applied_at, active_in_list
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (job_id, company, role, portal, job_url, applied_date, applied_at),
                )
                return cur.lastrowid

    def archive_application_ledger(
        self,
        job_id: str | None = None,
        job_url: str | None = None,
        app_id: int | None = None,
    ) -> int:
        """Mark an application as archived/removed from active list without deleting its historical ledger record."""
        now = _now_iso()
        updated = 0
        with self.conn:
            if app_id:
                app = self.get_application(app_id)
                if app:
                    job_id = job_id or app.get("job_id")
            if job_id or job_url:
                cur = self.conn.execute(
                    """
                    UPDATE application_ledger
                    SET active_in_list = 0, archived_at = ?
                    WHERE (job_id IS NOT NULL AND job_id != '' AND job_id = ?) 
                       OR (job_url IS NOT NULL AND job_url != '' AND job_url = ?)
                    """,
                    (now, job_id or "", job_url or ""),
                )
                updated += cur.rowcount
        return updated

    def get_dashboard_stats(self, period_months: int = 6) -> dict:
        """Compile complete analytics dashboard metrics and timelines (read-only)."""
        # 1. KPIs
        cur = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'interested'")
        saved_jobs = cur.fetchone()[0]

        cur = self.conn.execute("SELECT COUNT(*) FROM applications")
        active_applications = cur.fetchone()[0]

        cur = self.conn.execute("SELECT COUNT(*) FROM application_ledger")
        lifetime_applications = cur.fetchone()[0]

        cur = self.conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('applied', 'screening', 'interview', 'offer')")
        active_processes = cur.fetchone()[0]

        cur = self.conn.execute("""
            SELECT COUNT(DISTINCT a.id) FROM applications a
            LEFT JOIN application_events ae ON a.id = ae.application_id
            WHERE a.status = 'interview' 
               OR ae.stage LIKE '%entrevista%' 
               OR ae.stage LIKE '%interview%' 
               OR ae.stage LIKE '%coding%'
        """)
        interviews = cur.fetchone()[0]

        cur = self.conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'offer'")
        offers = cur.fetchone()[0]

        cur = self.conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'rejected'")
        rejected = cur.fetchone()[0]

        cur = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'discarded'")
        discarded_jobs = cur.fetchone()[0]

        conversion_rate = f"{round((interviews / lifetime_applications) * 100, 1)}%" if lifetime_applications > 0 else "0.0%"

        # 2. Monthly Timeline (Descending: most recent month first)
        today = date.today()
        month_names = {
            1: "jan.", 2: "fev.", 3: "mar.", 4: "abr.", 5: "mai.", 6: "jun.",
            7: "jul.", 8: "ago.", 9: "set.", 10: "out.", 11: "nov.", 12: "dez."
        }

        months_list = []
        year = today.year
        month = today.month
        current_ym = f"{year:04d}-{month:02d}"
        for _ in range(period_months):
            key = f"{year:04d}-{month:02d}"
            label = f"{month_names[month]}/{str(year)[2:]}"
            months_list.append((key, label))
            month -= 1
            if month == 0:
                month = 12
                year -= 1

        cur = self.conn.execute("""
            SELECT substr(applied_date, 1, 7) as ym,
                   COUNT(*) as total,
                   SUM(active_in_list) as active,
                   SUM(CASE WHEN active_in_list = 0 THEN 1 ELSE 0 END) as archived
            FROM application_ledger
            GROUP BY ym
        """)
        monthly_map = {row["ym"]: dict(row) for row in cur.fetchall()}

        monthly_timeline = []
        for key, label in months_list:
            m_data = monthly_map.get(key, {})
            monthly_timeline.append({
                "month_key": key,
                "label": label,
                "count": m_data.get("total", 0),
                "active": m_data.get("active", 0) or 0,
                "archived": m_data.get("archived", 0) or 0,
                "is_current": key == current_ym,
            })

        # 3. Daily Timeline (Last 30 days in descending order - most recent first)
        start_date = today - timedelta(days=29)
        daily_list = []
        cur_day = today
        while cur_day >= start_date:
            d_str = cur_day.isoformat()
            daily_list.append(d_str)
            cur_day -= timedelta(days=1)

        cur = self.conn.execute("""
            SELECT applied_date, COUNT(*) as total
            FROM application_ledger
            WHERE applied_date >= ?
            GROUP BY applied_date
        """, (start_date.isoformat(),))
        daily_map = {row["applied_date"]: row["total"] for row in cur.fetchall()}

        today_str = today.isoformat()
        yesterday_str = (today - timedelta(days=1)).isoformat()
        daily_timeline = []
        for d_str in daily_list:
            parts = d_str.split("-")
            short_label = f"{parts[2]}/{parts[1]}"
            daily_timeline.append({
                "date": d_str,
                "label": short_label,
                "count": daily_map.get(d_str, 0),
                "is_today": d_str == today_str,
                "is_yesterday": d_str == yesterday_str,
            })

        # 4. Status Distribution (Funnel)
        cur = self.conn.execute("""
            SELECT status, COUNT(*) as count FROM applications GROUP BY status
        """)
        app_status_counts = {row["status"]: row["count"] for row in cur.fetchall()}

        cur = self.conn.execute("SELECT COUNT(*) FROM application_ledger WHERE active_in_list = 0")
        archived_count = cur.fetchone()[0]

        total_funnel = saved_jobs + lifetime_applications
        def calc_pct(c):
            return round((c / total_funnel) * 100, 1) if total_funnel > 0 else 0.0

        status_distribution = [
            {"status": "saved", "label": "Salva (Interesse)", "count": saved_jobs, "percentage": calc_pct(saved_jobs), "color": "#38bdf8"},
            {"status": "applied", "label": "Candidatura enviada", "count": app_status_counts.get("applied", 0), "percentage": calc_pct(app_status_counts.get("applied", 0)), "color": "#60a5fa"},
            {"status": "screening", "label": "Triagem RH", "count": app_status_counts.get("screening", 0), "percentage": calc_pct(app_status_counts.get("screening", 0)), "color": "#818cf8"},
            {"status": "interview", "label": "Entrevista", "count": app_status_counts.get("interview", 0), "percentage": calc_pct(app_status_counts.get("interview", 0)), "color": "#a855f7"},
            {"status": "offer", "label": "Proposta Recebida", "count": app_status_counts.get("offer", 0), "percentage": calc_pct(app_status_counts.get("offer", 0)), "color": "#34d399"},
            {"status": "rejected", "label": "Recusada / Não seguiu", "count": app_status_counts.get("rejected", 0), "percentage": calc_pct(app_status_counts.get("rejected", 0)), "color": "#f87171"},
            {"status": "archived", "label": "Limpa da Lista (Histórico)", "count": archived_count, "percentage": calc_pct(archived_count), "color": "#94a3b8"},
        ]

        # 5. Portal Distribution
        portal_labels = {
            "gupy-search": "Gupy",
            "linkedin-search": "LinkedIn",
            "remotar-search": "Remotar",
            "greenhouse-search": "Greenhouse",
            "vagas-search": "Vagas.com",
            "solides-search": "Sólides",
            "programathor-search": "Programathor",
            "infojobs-search": "InfoJobs",
            "geekhunter-search": "GeekHunter",
            "trampos-search": "Trampos",
            "michaelpage-search": "Michael Page",
            "roberthalf-search": "Robert Half",
            "pcd-search": "PCD Online",
            "digai-search": "DigAÍ",
            "empregos-search": "Empregos.com.br",
            "freehire-search": "FreeHire",
            "linkedin_post": "LinkedIn (Post)",
            "hn-search": "Hacker News",
            "recruiter_radar": "Recrutadores",
        }
        cur = self.conn.execute("""
            SELECT COALESCE(NULLIF(portal, ''), 'manual') as portal_code, COUNT(*) as count
            FROM application_ledger
            GROUP BY portal_code
            ORDER BY count DESC
            LIMIT 8
        """)
        portal_distribution = []
        for r in cur.fetchall():
            code = r["portal_code"]
            label = portal_labels.get(code, code.replace("-search", "").capitalize() if code else "Outro")
            portal_distribution.append({
                "portal": code,
                "label": label,
                "count": r["count"],
            })

        # 6. Recent Activity
        cur = self.conn.execute("""
            SELECT id, company, role, portal, job_url, applied_date, active_in_list
            FROM application_ledger
            ORDER BY applied_date DESC, id DESC
            LIMIT 5
        """)
        recent_activity = [dict(r) for r in cur.fetchall()]

        return {
            "kpis": {
                "saved_jobs": saved_jobs,
                "active_applications": active_applications,
                "lifetime_applications": lifetime_applications,
                "active_processes": active_processes,
                "interviews": interviews,
                "offers": offers,
                "rejected": rejected,
                "discarded_jobs": discarded_jobs,
                "conversion_rate": conversion_rate,
            },
            "monthly_timeline": monthly_timeline,
            "daily_timeline": daily_timeline,
            "status_distribution": status_distribution,
            "portal_distribution": portal_distribution,
            "recent_activity": recent_activity,
        }

    # -----------------------------------------------------------------------
    # Recruiter Posts / Radar de Recrutadores
    # -----------------------------------------------------------------------
    def upsert_recruiter_post(self, post: dict) -> int:
        """Insert or update a recruiter post identified with emails."""
        emails_json = _serialize(post.get("emails", []))
        matched_kw_json = _serialize(post.get("matched_keywords", []))
        now = _now_iso()

        url = post.get("url")
        job_id = post.get("job_id")
        with self.conn:
            existing_row = None
            if url:
                cur = self.conn.execute("SELECT id FROM recruiter_posts WHERE url = ?", (url,))
                existing_row = cur.fetchone()
            if not existing_row and job_id:
                cur = self.conn.execute("SELECT id FROM recruiter_posts WHERE job_id = ?", (job_id,))
                existing_row = cur.fetchone()
            if existing_row:
                post_id = existing_row["id"]
                self.conn.execute("""
                    UPDATE recruiter_posts
                    SET emails = ?, email_context = ?, title = ?, company = ?,
                        portal = ?, location = ?, work_model = ?, published_date = ?,
                        description = ?, matched_keywords = ?, match_score = ?,
                        job_id = COALESCE(?, job_id)
                    WHERE id = ?
                """, (
                    emails_json, post.get("email_context"), post.get("title", "Oportunidade"),
                    post.get("company", "Empresa"), post.get("portal", "outros"),
                    post.get("location"), post.get("work_model"), post.get("published_date"),
                    post.get("description", ""), matched_kw_json, post.get("match_score", 0),
                    job_id, post_id
                ))
                return post_id

            cur = self.conn.execute("""
                INSERT INTO recruiter_posts (
                    emails, email_context, title, company, portal, url, location,
                    work_model, published_date, description, matched_keywords, match_score,
                    job_id, dismissed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (
                emails_json, post.get("email_context"), post.get("title", "Oportunidade"),
                post.get("company", "Empresa"), post.get("portal", "outros"),
                url, post.get("location"), post.get("work_model"), post.get("published_date"),
                post.get("description", ""), matched_kw_json, post.get("match_score", 0),
                post.get("job_id"), now
            ))
            return cur.lastrowid

    def get_latest_recruiter_post_for_job(self, job_id: str | None, url: str) -> dict | None:
        """Fetch latest recruiter_post description/metadata matching a job_id or URL."""
        cur = self.conn.execute(
            """
            SELECT description, title, company, location, work_model
            FROM recruiter_posts
            WHERE (? IS NOT NULL AND job_id = ?) OR url = ?
            ORDER BY id DESC LIMIT 1
            """,
            (job_id, job_id, url),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _norm_dedup_text(value: str | None) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", (value or "").lower())).strip()

    def find_recruiter_post_for_dedup(
        self,
        *,
        url: str | None = None,
        linkedin_activity_id: str | None = None,
        primary_email: str | None = None,
        description: str = "",
        title: str | None = None,
    ) -> dict | None:
        """Find an existing recruiter_posts row by URL, LinkedIn activity ID, or email+vacancy signature."""
        base_select = """
            SELECT rp.*, j.status AS job_status
            FROM recruiter_posts rp
            LEFT JOIN jobs j ON rp.job_id = j.id
        """
        clean_url = (url or "").strip()
        if clean_url:
            cur = self.conn.execute(f"{base_select} WHERE rp.url = ? ORDER BY rp.id DESC LIMIT 1", (clean_url,))
            row = cur.fetchone()
            if row:
                return dict(row)

        if linkedin_activity_id and linkedin_activity_id.isdigit():
            cur = self.conn.execute(
                f"{base_select} WHERE rp.url LIKE ? ORDER BY rp.id DESC LIMIT 1",
                (f"%{linkedin_activity_id}%",),
            )
            row = cur.fetchone()
            if row:
                return dict(row)

        norm_email = (primary_email or "").strip().lower()
        norm_prefix = " ".join((description or "").split())[:160].lower()
        cand_desc = self._norm_dedup_text(description)
        cand_title = self._norm_dedup_text(title)
        generic_titles = {"", "oportunidade", "vaga"}
        meaningful_cand_title = cand_title if cand_title not in generic_titles else ""
        if norm_email and (norm_prefix or meaningful_cand_title):
            cur = self.conn.execute(
                f"{base_select} WHERE LOWER(rp.emails) LIKE ? ORDER BY rp.id DESC LIMIT 50",
                (f"%{norm_email}%",),
            )
            for r in cur.fetchall():
                d = dict(r)
                row_emails = [
                    str(e).strip().lower()
                    for e in (_deserialize(d.get("emails")) or [])
                    if str(e).strip()
                ]
                if row_emails and norm_email not in row_emails:
                    continue

                existing_prefix = " ".join((d.get("description") or "").split())[:160].lower()
                existing_desc = self._norm_dedup_text(d.get("description"))
                existing_title = self._norm_dedup_text(d.get("title"))
                meaningful_existing_title = (
                    existing_title if existing_title not in generic_titles else ""
                )
                titles_conflict = bool(
                    meaningful_cand_title
                    and meaningful_existing_title
                    and meaningful_cand_title not in meaningful_existing_title
                    and meaningful_existing_title not in meaningful_cand_title
                )

                if norm_prefix and existing_prefix == norm_prefix and not titles_conflict:
                    if (
                        not cand_desc
                        or not existing_desc
                        or cand_desc == existing_desc
                        or cand_desc.startswith(existing_desc)
                        or existing_desc.startswith(cand_desc)
                        or cand_desc[:240] == existing_desc[:240]
                    ):
                        return d

                if cand_desc and existing_desc and not titles_conflict:
                    if len(cand_desc) >= 40 and len(existing_desc) >= 40 and (
                        cand_desc == existing_desc
                        or cand_desc.startswith(existing_desc)
                        or existing_desc.startswith(cand_desc)
                    ):
                        return d

                if (
                    meaningful_cand_title
                    and len(meaningful_cand_title) >= 12
                    and meaningful_cand_title == meaningful_existing_title
                ):
                    if not cand_desc or not existing_desc:
                        return d
                    if cand_desc[:80] == existing_desc[:80]:
                        return d
                    if len(set(cand_desc.split()) & set(existing_desc.split())) >= 6:
                        return d
        return None

    def list_recruiter_posts(
        self,
        query: str | None = None,
        only_cv: bool = False,
        portal: str | None = None,
        include_non_jobs: bool = True,
        only_untriaged: bool = False,
    ) -> list[dict]:
        """List active recruiter posts with optional keyword, CV match, portal and AI filters."""
        sql = """
            SELECT rp.*, j.status AS job_status
            FROM recruiter_posts rp
            LEFT JOIN jobs j ON rp.job_id = j.id
            WHERE rp.dismissed = 0
              AND TRIM(COALESCE(rp.emails, '')) NOT IN ('', '[]', 'null')
              AND (
                    rp.portal = 'linkedin_post'
                    OR (
                        COALESCE(rp.auto_promoted, 0) = 0
                        AND (rp.job_id IS NULL OR j.status IS NULL OR j.status NOT IN ('interested', 'applied', 'discarded', 'skipped'))
                    )
              )
              AND (rp.job_id IS NULL OR j.status IS NULL OR j.status NOT IN ('applied', 'discarded', 'skipped'))
        """
        params: list[Any] = []

        if only_cv:
            sql += """ AND (
                (rp.ai_evaluated_at IS NOT NULL AND rp.ai_classification = 'vaga_ativa' AND COALESCE(rp.ai_score, 0) >= 60)
                OR (rp.ai_evaluated_at IS NULL AND rp.ai_classification = 'vaga_ativa' AND COALESCE(rp.ai_score, 0) >= 60)
                OR (rp.ai_evaluated_at IS NULL AND rp.ai_classification IS NULL AND rp.match_score > 0)
            )"""

        if portal:
            sql += " AND rp.portal = ?"
            params.append(portal)

        if not include_non_jobs:
            sql += " AND COALESCE(rp.ai_classification, '') != 'nao_e_vaga'"

        if only_untriaged:
            sql += " AND rp.ai_evaluated_at IS NULL"

        if query and query.strip():
            terms = [t.strip() for t in query.split(",") if t.strip()]
            if terms:
                clauses = []
                for t in terms:
                    pattern = f"%{t}%"
                    clauses.append("(rp.title LIKE ? OR rp.company LIKE ? OR rp.description LIKE ? OR rp.emails LIKE ? OR rp.matched_keywords LIKE ?)")
                    params.extend([pattern, pattern, pattern, pattern, pattern])
                sql += " AND (" + " OR ".join(clauses) + ")"

        sql += """
            ORDER BY
                CASE WHEN rp.ai_classification = 'nao_e_vaga' THEN 1 ELSE 0 END ASC,
                COALESCE(rp.ai_score, rp.match_score) DESC,
                rp.published_date DESC,
                rp.id DESC
        """

        cur = self.conn.execute(sql, params)
        posts = []
        for r in cur.fetchall():
            d = dict(r)
            d["emails"] = _deserialize(d.get("emails")) or []
            d["matched_keywords"] = _deserialize(d.get("matched_keywords")) or []
            posts.append(d)
        return posts

    def get_recruiter_post(self, post_id: int) -> dict | None:
        """Fetch a single recruiter post by ID."""
        cur = self.conn.execute("SELECT * FROM recruiter_posts WHERE id = ?", (post_id,))
        r = cur.fetchone()
        if not r:
            return None
        d = dict(r)
        d["emails"] = _deserialize(d.get("emails")) or []
        d["matched_keywords"] = _deserialize(d.get("matched_keywords")) or []
        return d

    def update_recruiter_post_ai(
        self,
        post_id: int,
        classification: str,
        score: int | None,
        verdict: str | None,
        summary: str | None,
        best_email: str | None = None,
        auto_dismissed: bool = False,
        evaluated_at: str | None = None,
        ai_model: str | None = None,
    ) -> bool:
        """Persist AI triage metadata for a recruiter post (and optionally auto-dismiss)."""
        ts = evaluated_at or _now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE recruiter_posts
                SET ai_classification = ?,
                    ai_score = ?,
                    ai_verdict = ?,
                    ai_summary = ?,
                    ai_best_email = ?,
                    ai_model = COALESCE(?, ai_model),
                    ai_evaluated_at = ?,
                    dismissed = CASE WHEN ? THEN 1 ELSE dismissed END
                WHERE id = ?
                """,
                (
                    classification,
                    score,
                    verdict,
                    summary,
                    best_email or None,
                    ai_model or None,
                    ts,
                    1 if auto_dismissed else 0,
                    post_id,
                ),
            )
        return cur.rowcount > 0

    def get_latest_evaluation_providers(self, job_ids: list[str]) -> dict[str, str]:
        """Return the latest recorded ai_provider/model per job_id."""
        clean_ids = [jid for jid in dict.fromkeys(job_ids) if jid]
        if not clean_ids:
            return {}
        placeholders = ",".join("?" for _ in clean_ids)
        cur = self.conn.execute(
            f"""
            SELECT job_id, ai_provider
            FROM evaluations
            WHERE job_id IN ({placeholders}) AND ai_provider IS NOT NULL AND TRIM(ai_provider) != ''
            ORDER BY id ASC
            """,
            clean_ids,
        )
        out: dict[str, str] = {}
        for r in cur.fetchall():
            val = str(r["ai_provider"] or "").strip()
            if val and val.lower() != "antigravity":
                out[r["job_id"]] = val
        return out

    def get_latest_evaluation_details(self, job_ids: list[str]) -> dict[str, dict]:
        """Return latest subscores, gates, strengths, gaps, and ai_provider per job_id."""
        clean_ids = [jid for jid in dict.fromkeys(job_ids) if jid]
        if not clean_ids:
            return {}
        placeholders = ",".join("?" for _ in clean_ids)
        cur = self.conn.execute(
            f"""
            SELECT job_id, score_technical, score_experience, score_behavioral,
                   score_location, score_career, score_global, verdict,
                   strengths, gaps, language_gate, language_note, ai_provider
            FROM evaluations
            WHERE job_id IN ({placeholders})
            ORDER BY id ASC
            """,
            clean_ids,
        )
        out: dict[str, dict] = {}
        for r in cur.fetchall():
            row = self._row_to_dict(r, self.EVAL_JSON_FIELDS) or {}
            jid = row.get("job_id")
            if not jid:
                continue
            detail: dict[str, Any] = {}
            t, e, b, c = (
                row.get("score_technical"),
                row.get("score_experience"),
                row.get("score_behavioral"),
                row.get("score_career"),
            )
            if None not in (t, e, b, c):
                detail["subscores"] = {
                    "technical": int(t),
                    "experience": int(e),
                    "behavioral": int(b),
                    "career": int(c),
                }
            if row.get("score_location"):
                detail["location_verdict"] = row["score_location"]
            if row.get("strengths"):
                detail["strengths"] = row["strengths"]
            if row.get("gaps"):
                detail["gaps"] = row["gaps"]
            if row.get("language_gate"):
                detail["language_gate"] = row["language_gate"]
            if row.get("language_note"):
                detail["language_note"] = row["language_note"]
            prov = str(row.get("ai_provider") or "").strip()
            if prov and prov.lower() != "antigravity":
                detail["ai_model"] = prov
            out[jid] = detail
        return out

    def mark_recruiter_post_promoted(
        self,
        post_id: int,
        job_id: str,
        run_id: str | None = None,
    ) -> bool:
        """Link a recruiter post to its promoted job row and mark auto-promotion provenance."""
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE recruiter_posts
                SET job_id = ?,
                    auto_promoted = 1,
                    auto_run_id = ?,
                    dismissed = 0
                WHERE id = ?
                """,
                (job_id, run_id, post_id),
            )
        return cur.rowcount > 0

    def clear_recruiter_post_promotion(
        self,
        job_id: str | None = None,
        run_id: str | None = None,
    ) -> int:
        """Revert auto-promotion flag on recruiter_posts while preserving AI triage cache."""
        if not job_id and not run_id:
            return 0
        with self.conn:
            if job_id:
                cur = self.conn.execute(
                    "UPDATE recruiter_posts SET auto_promoted = 0, auto_run_id = NULL WHERE job_id = ?",
                    (job_id,),
                )
            else:
                cur = self.conn.execute(
                    "UPDATE recruiter_posts SET auto_promoted = 0, auto_run_id = NULL WHERE auto_run_id = ?",
                    (run_id,),
                )
        return cur.rowcount

    def get_recruiter_context_for_jobs(
        self,
        job_ids: list[str],
        urls: list[str] | None = None,
    ) -> dict[str, dict]:
        """Map job_id / url -> recruiter context (ordered emails, post_id, contacted_email, contacted_at, description)."""
        clean_ids = [jid for jid in job_ids if jid]
        clean_urls = [u for u in (urls or []) if u]
        if not clean_ids and not clean_urls:
            return {}

        clauses: list[str] = []
        params: list[Any] = []
        if clean_ids:
            ph = ",".join("?" for _ in clean_ids)
            clauses.append(f"job_id IN ({ph})")
            params.extend(clean_ids)
        if clean_urls:
            ph = ",".join("?" for _ in clean_urls)
            clauses.append(f"url IN ({ph})")
            params.extend(clean_urls)

        cur = self.conn.execute(
            f"""
            SELECT id, job_id, url, emails, ai_best_email, contacted_email, contacted_at, description
            FROM recruiter_posts
            WHERE {' OR '.join(clauses)}
            """,
            params,
        )
        mapping: dict[str, dict] = {}
        for r in cur.fetchall():
            emails = _deserialize(r["emails"]) or []
            if not isinstance(emails, list):
                emails = []
            best = (r["ai_best_email"] or "").strip()
            ordered: list[str] = []
            if best:
                ordered.append(best)
            for em in emails:
                em_s = str(em).strip()
                if em_s and em_s not in ordered:
                    ordered.append(em_s)
            if not ordered and not r["contacted_email"]:
                continue
            ctx = {
                "post_id": r["id"],
                "emails": ordered,
                "contacted_email": (r["contacted_email"] or "").strip() or None,
                "contacted_at": r["contacted_at"],
                "description": r["description"] or "",
            }
            if r["job_id"]:
                mapping[f"id:{r['job_id']}"] = ctx
            if r["url"]:
                mapping[f"url:{r['url']}"] = ctx
        return mapping

    def get_recruiter_emails_for_jobs(
        self,
        job_ids: list[str],
        urls: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """Map job_id / url -> ordered direct recruiter email list (best email first)."""
        contexts = self.get_recruiter_context_for_jobs(job_ids, urls)
        return {
            key: ctx["emails"]
            for key, ctx in contexts.items()
            if ctx.get("emails")
        }

    def get_contacted_recruiter_emails(self) -> dict[str, dict]:
        """Return active contacted recruiter emails keyed by lowercase address."""
        contacted: dict[str, dict] = {}

        def _store(email_val: str | None, info: dict) -> None:
            em = (email_val or "").strip().lower()
            if not em:
                return
            existing = contacted.get(em)
            if not existing or (info.get("contacted_at") or "") > (existing.get("contacted_at") or ""):
                contacted[em] = info

        cur = self.conn.execute("""
            SELECT rp.id as post_id, rp.contacted_email, rp.contacted_at,
                   COALESCE(NULLIF(rp.company, ''), j.company, '') as company,
                   COALESCE(NULLIF(rp.title, ''), j.title, '') as title,
                   rp.job_id,
                   a.id as application_id,
                   a.applied_date
            FROM recruiter_posts rp
            LEFT JOIN jobs j ON rp.job_id = j.id
            LEFT JOIN applications a ON a.job_id = rp.job_id
            WHERE rp.contacted_email IS NOT NULL AND TRIM(rp.contacted_email) != ''
              AND (a.id IS NOT NULL OR COALESCE(j.status, '') = 'applied')
        """)
        for r in cur.fetchall():
            ts = r["contacted_at"] or r["applied_date"] or ""
            _store(r["contacted_email"], {
                "email": (r["contacted_email"] or "").strip(),
                "company": r["company"] or "",
                "title": r["title"] or "",
                "contacted_at": ts,
                "job_id": r["job_id"],
                "application_id": r["application_id"],
            })

        cur2 = self.conn.execute("""
            SELECT a.id as application_id, a.contacted_email, a.applied_date, a.updated_at,
                   a.job_id, j.company, j.title
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.contacted_email IS NOT NULL AND TRIM(a.contacted_email) != ''
        """)
        for r in cur2.fetchall():
            ts = r["applied_date"] or (r["updated_at"] or "")[:10]
            _store(r["contacted_email"], {
                "email": (r["contacted_email"] or "").strip(),
                "company": r["company"] or "",
                "title": r["title"] or "",
                "contacted_at": ts,
                "job_id": r["job_id"],
                "application_id": r["application_id"],
            })

        return contacted

    def mark_recruiter_post_contacted(
        self,
        post_id: int,
        job_id: str,
        contacted_email: str,
        contacted_at: str | None = None,
    ) -> bool:
        """Link a recruiter post to its applied job and record contacted email/timestamp."""
        ts = contacted_at or _now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE recruiter_posts
                SET job_id = ?,
                    contacted_email = ?,
                    contacted_at = ?,
                    auto_promoted = 0,
                    dismissed = 0
                WHERE id = ?
                """,
                (job_id, contacted_email.strip().lower(), ts, post_id),
            )
        return cur.rowcount > 0

    def reopen_recruiter_post_from_application(
        self,
        app_id: int | None = None,
        job_id: str | None = None,
        job_url: str | None = None,
        recruiter_post_id: int | None = None,
    ) -> dict | None:
        """Delete application, archive ledger, reset job status to 'new' and restore recruiter post."""
        now = _now_iso()
        target_job_id = job_id
        target_url = (job_url or "").strip()

        if app_id:
            app = self.get_application(app_id)
            if app:
                target_job_id = target_job_id or app.get("job_id")
                if not recruiter_post_id:
                    recruiter_post_id = app.get("recruiter_post_id")

        if not target_job_id and target_url:
            job = self.get_job_by_url(target_url)
            if job:
                target_job_id = job["id"]

        if target_job_id and not target_url:
            job = self.get_job(target_job_id)
            if job:
                target_url = job.get("url") or ""

        # Locate matching recruiter_posts rows before deleting application
        clauses: list[str] = []
        params: list[Any] = []
        if recruiter_post_id:
            clauses.append("id = ?")
            params.append(recruiter_post_id)
        if target_job_id:
            clauses.append("job_id = ?")
            params.append(target_job_id)
        if target_url:
            clauses.append("url = ?")
            params.append(target_url)

        matched_posts: list[dict] = []
        if clauses:
            cur = self.conn.execute(
                f"SELECT id, job_id, url FROM recruiter_posts WHERE {' OR '.join(clauses)}",
                params,
            )
            matched_posts = [dict(r) for r in cur.fetchall()]
            if matched_posts and not recruiter_post_id:
                recruiter_post_id = matched_posts[0]["id"]
            if matched_posts and not target_job_id:
                target_job_id = matched_posts[0].get("job_id")

        if not matched_posts and not recruiter_post_id and not target_url.startswith("recruiter://"):
            return None

        with self.conn:
            if app_id:
                self.conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            if target_job_id:
                self.conn.execute("DELETE FROM applications WHERE job_id = ?", (target_job_id,))

            if target_job_id or target_url:
                self.conn.execute(
                    """
                    UPDATE application_ledger
                    SET active_in_list = 0, archived_at = ?
                    WHERE (job_id IS NOT NULL AND job_id != '' AND job_id = ?)
                       OR (job_url IS NOT NULL AND job_url != '' AND job_url = ?)
                    """,
                    (now, target_job_id or "", target_url or ""),
                )

            if target_job_id:
                row = self.conn.execute(
                    "SELECT status FROM jobs WHERE id = ?", (target_job_id,)
                ).fetchone()
                old_status = row["status"] if row else None
                self.conn.execute(
                    "UPDATE jobs SET status = 'new', updated_at = ? WHERE id = ?",
                    (now, target_job_id),
                )
                self.conn.execute(
                    """
                    INSERT INTO status_log (job_id, from_status, to_status, source, note, created_at)
                    VALUES (?, ?, 'new', 'reopen_recruiter', 'Reaberto para Recrutadores', ?)
                    """,
                    (target_job_id, old_status, now),
                )

            if clauses:
                self.conn.execute(
                    f"""
                    UPDATE recruiter_posts
                    SET contacted_email = NULL,
                        contacted_at = NULL,
                        dismissed = 0,
                        auto_promoted = 0,
                        auto_run_id = NULL
                    WHERE {' OR '.join(clauses)}
                    """,
                    params,
                )

        return {
            "post_id": recruiter_post_id,
            "job_id": target_job_id,
            "url": target_url,
        }

    def dismiss_recruiter_post(self, post_id: int) -> bool:
        """Soft delete a recruiter post by setting dismissed = 1."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE recruiter_posts SET dismissed = 1 WHERE id = ?",
                (post_id,)
            )
        return cur.rowcount > 0

    def dismiss_recruiter_posts(self, post_ids: list[int]) -> list[int]:
        """Soft delete multiple recruiter posts by setting dismissed = 1 in safe chunks."""
        clean_ids: list[int] = []
        seen: set[int] = set()
        for raw_id in post_ids or []:
            try:
                pid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if pid > 0 and pid not in seen:
                seen.add(pid)
                clean_ids.append(pid)

        if not clean_ids:
            return []

        dismissed_ids: list[int] = []
        with self.conn:
            for idx in range(0, len(clean_ids), 500):
                chunk = clean_ids[idx:idx + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = self.conn.execute(
                    f"SELECT id FROM recruiter_posts WHERE id IN ({placeholders}) AND COALESCE(dismissed, 0) = 0",
                    chunk,
                ).fetchall()
                existing = {int(row["id"]) for row in rows}
                if not existing:
                    continue
                self.conn.execute(
                    f"UPDATE recruiter_posts SET dismissed = 1 WHERE id IN ({placeholders}) AND COALESCE(dismissed, 0) = 0",
                    chunk,
                )
                dismissed_ids.extend(pid for pid in chunk if pid in existing)
        return dismissed_ids

    def get_jobs_with_potential_emails(self) -> list[dict]:
        """Fetch active/pending jobs from DB whose description mentions an email symbol (@)."""
        cur = self.conn.execute("""
            SELECT id, title, company, portal, url, location, work_model, posted_date, description
            FROM jobs
            WHERE description IS NOT NULL
              AND description LIKE '%@%'
              AND COALESCE(url, '') NOT LIKE 'recruiter://%'
              AND COALESCE(status, 'new') NOT IN ('discarded', 'applied', 'skipped')
        """)
        return [dict(r) for r in cur.fetchall()]

    def get_interested_status_metadata(
        self, job_ids: list[str]
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        """Fetch saved_at timestamps and auto-promotion provenance for interested jobs."""
        clean_ids = [jid for jid in job_ids if jid]
        if not clean_ids:
            return {}, {}
        placeholders = ",".join("?" for _ in clean_ids)
        cur = self.conn.execute(
            f"""
            SELECT job_id, created_at, source, note
            FROM status_log
            WHERE to_status = 'interested' AND job_id IN ({placeholders})
            ORDER BY id ASC
            """,
            clean_ids,
        )
        saved_at_map: dict[str, str] = {}
        auto_meta_map: dict[str, dict[str, Any]] = {}
        for r in cur.fetchall():
            jid = r["job_id"]
            saved_at_map[jid] = r["created_at"]
            src = r["source"] or ""
            note = r["note"] or ""
            is_auto = src in ("auto_triage", "auto_triage_recruiter")
            m_run = re.search(r"\[auto:([A-Za-z0-9_-]+)\]", note)
            auto_meta_map[jid] = {
                "auto_promoted": is_auto,
                "auto_origin": (
                    "recruiter"
                    if src == "auto_triage_recruiter"
                    else ("jobs" if src == "auto_triage" else None)
                ),
                "auto_run_id": m_run.group(1) if (is_auto and m_run) else None,
            }
        return saved_at_map, auto_meta_map

    def clear_discarded_jobs(self) -> int:
        """Delete discarded/low-skipped jobs and their discarded status log entries."""
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM jobs WHERE status = 'discarded' OR (status = 'skipped' AND fit = 'low')"
            )
            deleted_count = cur.rowcount
            self.conn.execute("DELETE FROM status_log WHERE to_status = 'discarded'")
        return deleted_count


