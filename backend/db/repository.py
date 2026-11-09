"""Data Access Layer (Repository) for Vagamundo v2."""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Any, Optional

from backend.db import get_db, ROOT

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


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
        self.conn = get_db(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        if SCHEMA_PATH.exists():
            schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
            self.conn.executescript(schema_sql)
        self._backfill_ledger()

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
        except Exception:
            pass

    def close(self) -> None:
        if self.conn:
            self.conn.close()

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
            except Exception:
                job_id = f"job-{abs(hash(url or title + company))}"

        now = _now_iso()

        # Check existing by id or url
        cur = self.conn.execute("SELECT id, created_at, status, fit, rank_score, rank_verdict FROM jobs WHERE id = ? OR url = ?", (job_id, url))
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

        work_model = job.get("work_model") or job.get("workplace_type")
        contract_type = job.get("contract_type") or job.get("contract")
        posted_date = job.get("posted_date") or job.get("date")

        with self.conn:
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
        query = "SELECT * FROM jobs WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if fit:
            query += " AND fit = ?"
            params.append(fit)
        if portal:
            query += " AND portal = ?"
            params.append(portal)
        if q:
            query += " AND (title LIKE ? OR company LIKE ? OR description LIKE ?)"
            term = f"%{q}%"
            params.extend([term, term, term])

        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
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
        query = "SELECT COUNT(*) as cnt FROM jobs WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if fit:
            query += " AND fit = ?"
            params.append(fit)
        if portal:
            query += " AND portal = ?"
            params.append(portal)
        if q:
            query += " AND (title LIKE ? OR company LIKE ? OR description LIKE ?)"
            term = f"%{q}%"
            params.extend([term, term, term])

        cur = self.conn.execute(query, params)
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
                    strengths, gaps, report_md, ai_provider, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        location_verdict = ?,
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
                        _serialize(eval_data.get("strengths")),
                        _serialize(eval_data.get("gaps")),
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
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        app.get("status", "applied"),
                        app.get("cv_path"),
                        app.get("cover_letter_path"),
                        app.get("interview_notes_path"),
                        app.get("applied_date", now[:10]),
                        app.get("notes"),
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
        """Compile complete analytics dashboard metrics and timelines."""
        self._backfill_ledger()

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
        if url:
            cur = self.conn.execute("SELECT id FROM recruiter_posts WHERE url = ?", (url,))
            row = cur.fetchone()
            if row:
                post_id = row["id"]
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
                    post.get("job_id"), post_id
                ))
                self.conn.commit()
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
        self.conn.commit()
        return cur.lastrowid

    def list_recruiter_posts(
        self,
        query: str | None = None,
        only_cv: bool = False,
        portal: str | None = None
    ) -> list[dict]:
        """List recruiter posts with optional keyword filtering and CV match."""
        sql = "SELECT * FROM recruiter_posts WHERE dismissed = 0"
        params: list[Any] = []

        if only_cv:
            sql += " AND match_score > 0"

        if portal:
            sql += " AND portal = ?"
            params.append(portal)

        if query and query.strip():
            terms = [t.strip() for t in query.split(",") if t.strip()]
            if terms:
                clauses = []
                for t in terms:
                    pattern = f"%{t}%"
                    clauses.append("(title LIKE ? OR company LIKE ? OR description LIKE ? OR emails LIKE ? OR matched_keywords LIKE ?)")
                    params.extend([pattern, pattern, pattern, pattern, pattern])
                sql += " AND (" + " OR ".join(clauses) + ")"

        sql += " ORDER BY match_score DESC, published_date DESC, id DESC"

        cur = self.conn.execute(sql, params)
        posts = []
        for r in cur.fetchall():
            d = dict(r)
            d["emails"] = _deserialize(d.get("emails")) or []
            d["matched_keywords"] = _deserialize(d.get("matched_keywords")) or []
            posts.append(d)
        return posts

    def dismiss_recruiter_post(self, post_id: int) -> bool:
        """Soft delete a recruiter post by setting dismissed = 1."""
        cur = self.conn.execute(
            "UPDATE recruiter_posts SET dismissed = 1 WHERE id = ?",
            (post_id,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_jobs_with_potential_emails(self) -> list[dict]:
        """Fetch all jobs from DB whose description mentions an email symbol (@)."""
        cur = self.conn.execute("""
            SELECT id, title, company, portal, url, location, work_model, posted_date, description
            FROM jobs
            WHERE description IS NOT NULL AND description LIKE '%@%'
        """)
        return [dict(r) for r in cur.fetchall()]


