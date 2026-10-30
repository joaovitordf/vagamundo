"""Liveness checking service to detect expired or closed job postings."""

from __future__ import annotations
import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from backend.db.repository import Repository

DEAD_PATTERNS = [
    re.compile(r"vaga\s+(?:foi\s+)?encerrada", re.I),
    re.compile(r"processo\s+seletivo\s+(?:foi\s+)?encerrado", re.I),
    re.compile(r"vaga\s+(?:n[ãa]o\s+est[áa]\s+mais\s+dispon[íi]vel|desativada|expirada)", re.I),
    re.compile(r"esta\s+oportunidade\s+n[ãa]o\s+est[áa]\s+mais\s+aberta", re.I),
    re.compile(r"job\s+(?:is\s+)?no\s+longer\s+available", re.I),
    re.compile(r"this\s+posting\s+has\s+expired", re.I),
    re.compile(r"position\s+has\s+been\s+filled", re.I),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LivenessService:
    """Probes URLs and ATS endpoints to verify if postings are still live."""

    def __init__(self, repo: Optional[Repository] = None, timeout: float = 10.0, max_concurrency: int = 5):
        self.repo = repo or Repository()
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def probe_url(self, client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
        """Probe a single URL to check liveness."""
        now = _now_iso()
        async with self.semaphore:
            try:
                # 1. Try HEAD request first
                try:
                    resp = await client.head(url, timeout=self.timeout, follow_redirects=True)
                except httpx.HTTPError:
                    resp = None

                # Fallback to GET if HEAD failed, returned 405 Method Not Allowed, or returned 403
                if resp is None or resp.status_code in (405, 403):
                    resp = await client.get(url, timeout=self.timeout, follow_redirects=True)

                if resp.status_code in (404, 410):
                    return {
                        "url": url,
                        "alive": False,
                        "reason": f"HTTP {resp.status_code}",
                        "checked_at": now,
                    }

                if resp.status_code >= 500:
                    return {
                        "url": url,
                        "alive": None,
                        "reason": f"HTTP {resp.status_code} (inconclusive)",
                        "checked_at": now,
                    }

                # Check text body for dead job patterns
                if resp.status_code == 200:
                    text_sample = resp.text[:15000]
                    for pattern in DEAD_PATTERNS:
                        if pattern.search(text_sample):
                            return {
                                "url": url,
                                "alive": False,
                                "reason": "posting_closed_text",
                                "checked_at": now,
                            }
                    return {
                        "url": url,
                        "alive": True,
                        "reason": "OK",
                        "checked_at": now,
                    }

                return {
                    "url": url,
                    "alive": None,
                    "reason": f"HTTP {resp.status_code}",
                    "checked_at": now,
                }
            except httpx.TimeoutException:
                return {
                    "url": url,
                    "alive": None,
                    "reason": "timeout",
                    "checked_at": now,
                }
            except Exception as exc:
                return {
                    "url": url,
                    "alive": None,
                    "reason": str(exc),
                    "checked_at": now,
                }

    async def check(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Check liveness of multiple URLs concurrently."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
        async with httpx.AsyncClient(headers=headers, verify=False) as client:
            tasks = [self.probe_url(client, u) for u in urls]
            results = await asyncio.gather(*tasks, return_exceptions=False)

        # Update SQLite status for definitively dead jobs
        for r in results:
            if r.get("alive") is False:
                job = self.repo.get_job_by_url(r["url"])
                if job and job["status"] not in ("applied", "interested"):
                    self.repo.mark_jobs([job["id"]], decision="expired", source="liveness", note=r.get("reason", ""))

        return results

    async def sweep_expired(self, max_age_days: int = 30) -> int:
        """Sweep older jobs from SQLite and check their liveness."""
        cur = self.repo.conn.execute(
            "SELECT url FROM jobs WHERE status IN ('new', 'ranked') LIMIT 100"
        )
        urls = [row["url"] for row in cur.fetchall() if row["url"]]
        if not urls:
            return 0
        results = await self.check(urls)
        return sum(1 for r in results if r.get("alive") is False)

