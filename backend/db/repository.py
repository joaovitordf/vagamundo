"""Data Access Layer (Repository) for Vagamundo v2."""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
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

        # Generate canonical slug key if id is missing or numeric portal ID
        if not job_id or (isinstance(job_id, str) and (job_id.isdigit() or not ("-" in job_id or "_" in job_id))):
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

