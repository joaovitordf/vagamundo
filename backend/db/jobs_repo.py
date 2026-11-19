"""Jobs and AI Evaluations repository mixin."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import date
from typing import Any

from backend.core.constants import APPLIED_PIPELINE_STATUSES
from backend.db.utils import now_iso, row_to_dict, serialize

logger = logging.getLogger(__name__)


class JobsRepositoryMixin:
    """SQLite operations for jobs, status_log, evaluations, and discarded cleanup."""

    JOB_JSON_FIELDS = ("strengths", "gaps", "signals", "also_on", "full_posting")
    EVAL_JSON_FIELDS = ("strengths", "gaps")

    def upsert_job(self, job: dict) -> str:
        """Insert or update a job posting in the database."""
        job_id = job.get("id")
        title = job.get("title", "")
        company = job.get("company", "")
        url = job.get("url", "")

        if not job_id or (isinstance(job_id, str) and job_id.isdigit()):
            try:
                from backend.tools.job_key import make_key

                job_id = make_key(company, title, url)
            except (ImportError, ValueError, TypeError):
                seed = (url or f"{company}|{title}").encode("utf-8", errors="ignore")
                job_id = f"job-{hashlib.sha256(seed).hexdigest()[:12]}"

        now = now_iso()
        work_model = job.get("work_model") or job.get("workplace_type")
        contract_type = job.get("contract_type") or job.get("contract")
        posted_date = job.get("posted_date") or job.get("date")

        with self.conn:
            cur = self.conn.execute(
                "SELECT id, created_at, status, fit, rank_score, rank_verdict FROM jobs WHERE id = ? OR (? != '' AND url = ?)",
                (job_id, url, url),
            )
            row = cur.fetchone()

            status = job.get("status") or (row["status"] if row else "new")
            fit = job.get("fit") or (row["fit"] if row else None)

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
                        serialize(job.get("strengths")),
                        serialize(job.get("gaps")),
                        serialize(job.get("signals")),
                        serialize(job.get("also_on")),
                        serialize(job.get("full_posting")),
                        now,
                        target_id,
                    ),
                )
                return target_id

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
                    serialize(job.get("strengths")),
                    serialize(job.get("gaps")),
                    serialize(job.get("signals")),
                    serialize(job.get("also_on")),
                    serialize(job.get("full_posting")),
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
        ph = ",".join(f"'{s}'" for s in APPLIED_PIPELINE_STATUSES)
        queries = (
            "SELECT job_url AS url, company, role AS title FROM application_ledger",
            f"SELECT url, company, title FROM jobs WHERE status IN ({ph})",
        )
        for sql in queries:
            try:
                cur = self.conn.execute(sql)
                rows.extend(dict(r) for r in cur.fetchall())
            except sqlite3.Error as exc:
                logger.warning("Failed to query applied index: %s", exc)
        return rows

    def fill_missing_job_metadata(self, job_id: str, metadata: dict) -> None:
        """Backfill empty location, work_model, posted_date, description, and portal columns on a job."""
        with self.conn:
            self.conn.execute(
                """
                UPDATE jobs SET
                    location = COALESCE(NULLIF(TRIM(location), ''), ?),
                    work_model = COALESCE(NULLIF(TRIM(work_model), ''), ?),
                    posted_date = COALESCE(NULLIF(TRIM(posted_date), ''), ?),
                    description = COALESCE(NULLIF(TRIM(description), ''), ?),
                    portal = COALESCE(NULLIF(TRIM(portal), ''), ?)
                WHERE id = ?
                """,
                (
                    metadata.get("location"),
                    metadata.get("work_model"),
                    metadata.get("posted_date"),
                    metadata.get("description"),
                    metadata.get("portal"),
                    job_id,
                ),
            )

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
                    now_iso(),
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

        now = now_iso()
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

    def insert_evaluation(self, eval_data: dict) -> int:
        """Insert an AI evaluation score report and synchronize summary fields on jobs."""
        now = now_iso()
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
                    serialize(eval_data.get("strengths")),
                    serialize(eval_data.get("gaps")),
                    eval_data.get("language_gate"),
                    eval_data.get("language_note"),
                    eval_data.get("report_md"),
                    eval_data.get("ai_provider"),
                    now,
                ),
            )
            eval_id = cur.lastrowid

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
                        serialize(eval_data.get("strengths")) if eval_data.get("strengths") else None,
                        serialize(eval_data.get("gaps")) if eval_data.get("gaps") else None,
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
            row = row_to_dict(r, self.EVAL_JSON_FIELDS) or {}
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
            for src_key, dst_key in (
                ("score_location", "location_verdict"),
                ("strengths", "strengths"),
                ("gaps", "gaps"),
                ("language_gate", "language_gate"),
                ("language_note", "language_note"),
            ):
                if row.get(src_key):
                    detail[dst_key] = row[src_key]
            prov = str(row.get("ai_provider") or "").strip()
            if prov and prov.lower() != "antigravity":
                detail["ai_model"] = prov
            out[jid] = detail
        return out

    def delete_discarded_jobs_by_urls(self, urls: list[str]) -> dict[str, int]:
        """Permanently delete specific discarded/low-skipped jobs and linked recruiter_posts from SQLite."""
        clean_urls = [u.strip() for u in dict.fromkeys(urls or []) if isinstance(u, str) and u.strip()]
        if not clean_urls:
            return {"deleted_db": 0, "deleted_recruiter_posts": 0}

        deleted_jobs = 0
        deleted_posts = 0
        with self.conn:
            for idx in range(0, len(clean_urls), 400):
                chunk = clean_urls[idx:idx + 400]
                ph = ",".join("?" for _ in chunk)
                rows = self.conn.execute(
                    f"""
                    SELECT id, url FROM jobs
                    WHERE url IN ({ph})
                      AND (status = 'discarded' OR (status = 'skipped' AND fit = 'low'))
                    """,
                    chunk,
                ).fetchall()
                target_jids = [r["id"] for r in rows]
                target_urls = [r["url"] for r in rows if r["url"]]
                if not target_jids:
                    continue
                deleted_posts += self._delete_linked_recruiter_posts(target_jids, target_urls)
                j_ph = ",".join("?" for _ in target_jids)
                cur = self.conn.execute(
                    f"DELETE FROM jobs WHERE id IN ({j_ph})",
                    target_jids,
                )
                deleted_jobs += cur.rowcount
        return {"deleted_db": deleted_jobs, "deleted_recruiter_posts": deleted_posts}

    def clear_discarded_jobs(self) -> int:
        """Delete discarded/low-skipped jobs, linked recruiter_posts, and their discarded status log entries."""
        with self.conn:
            rows = self.conn.execute(
                "SELECT id, url FROM jobs WHERE status = 'discarded' OR (status = 'skipped' AND fit = 'low')"
            ).fetchall()
            target_jids = [r["id"] for r in rows]
            target_urls = [r["url"] for r in rows if r["url"]]
            if target_jids or target_urls:
                self._delete_linked_recruiter_posts(target_jids, target_urls)
            cur = self.conn.execute(
                "DELETE FROM jobs WHERE status = 'discarded' OR (status = 'skipped' AND fit = 'low')"
            )
            deleted_count = cur.rowcount
            self.conn.execute("DELETE FROM status_log WHERE to_status = 'discarded'")
        return deleted_count
