"""Applications, timeline events, and historical ledger repository mixin."""

from __future__ import annotations

from typing import Any

from backend.db.utils import now_iso


class ApplicationsRepositoryMixin:
    """SQLite operations for applications, application_events, and application_ledger."""

    def upsert_application(self, app: dict) -> int:
        """Insert or update an application tracker row."""
        app_id = app.get("id")
        job_id = app.get("job_id")
        now = now_iso()

        with self.conn:
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
            if job_id:
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

    def insert_application_event(self, event_data: dict) -> int:
        """Insert an interview stage, feedback, or Q&A event."""
        now = now_iso()
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
        now = now_iso()
        applied_date = applied_date or now[:10]
        applied_at = applied_at or now

        if not (company and company.strip()) or not (role and role.strip()) or not (job_url and job_url.strip()):
            return 0

        with self.conn:
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
        now = now_iso()
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
