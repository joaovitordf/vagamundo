"""Tracker service orchestrating persistence and transitions."""

from __future__ import annotations
from pathlib import Path
from typing import Any

from backend.db.repository import Repository


class TrackerService:
    """Manages job tracking state, transitions, dedup, and applications."""

    def __init__(self, repo: Repository | None = None, db_path: str | Path | None = None):
        self.repo = repo if repo is not None else Repository(db_path)

    def is_seen(self, url: str | None = None, company: str | None = None, title: str | None = None) -> bool:
        """Check whether a posting has already been recorded by URL or (company, title)."""
        if url:
            job = self.repo.get_job_by_url(url)
            if job:
                return True
        if company and title:
            # Check company and title match
            cur = self.repo.conn.execute(
                "SELECT id FROM jobs WHERE LOWER(TRIM(company)) = LOWER(TRIM(?)) AND LOWER(TRIM(title)) = LOWER(TRIM(?)) LIMIT 1",
                (company, title),
            )
            if cur.fetchone():
                return True
        return False

    def upsert_job(self, job: dict) -> str:
        return self.repo.upsert_job(job)

    def get_job(self, job_id: str) -> dict | None:
        return self.repo.get_job(job_id)

    def list_jobs(
        self,
        status: str | None = None,
        fit: str | None = None,
        portal: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        return self.repo.list_jobs(
            status=status,
            fit=fit,
            portal=portal,
            q=q,
            limit=limit,
            offset=offset,
        )

    def count_jobs(
        self,
        status: str | None = None,
        fit: str | None = None,
        portal: str | None = None,
        q: str | None = None,
    ) -> int:
        return self.repo.count_jobs(status=status, fit=fit, portal=portal, q=q)

    def mark_jobs(
        self,
        ids: list[str],
        decision: str,
        source: str = "cli",
        note: str = "",
    ) -> int:
        return self.repo.mark_jobs(ids=ids, decision=decision, source=source, note=note)

    def record_evaluation(self, eval_data: dict) -> int:
        return self.repo.insert_evaluation(eval_data)

    def get_evaluation(self, job_id: str) -> dict | None:
        return self.repo.get_evaluation(job_id)

    def record_application(self, app_data: dict) -> int:
        return self.repo.upsert_application(app_data)

    def list_applications(self, status: str | None = None) -> list[dict]:
        return self.repo.list_applications(status=status)

    def record_scan_run(self, run_data: dict) -> int:
        return self.repo.insert_scan_run(run_data)

