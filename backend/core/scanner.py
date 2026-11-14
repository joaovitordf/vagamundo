"""Scanner service coordinating portal job searches with real-time progress streaming."""

from __future__ import annotations
import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.constants import LOW_SCORE_AUTO_DISCARD_THRESHOLD, ROOT
from backend.db.repository import Repository
from backend.tools import painel, scrape_run

logger = logging.getLogger(__name__)


def default_results_path(day: str | None = None) -> Path:
    return Path(tempfile.gettempdir()) / f"painel_busca_{day or date.today().isoformat()}.json"


class ScannerService:
    """Manages asynchronous job scanning across configured portals with progress reporting."""

    def __init__(self, out_path: Path | None = None, repo: Repository | None = None):
        self.out = out_path or default_results_path()
        self.repo = repo or Repository()
        self.lock = threading.Lock()
        self.running = False
        self.started: Optional[str] = None
        self.error: Optional[str] = None
        self.summary: Optional[str] = None
        self.progress: Dict[str, Any] = {
            "percent": 0.0,
            "completed": 0,
            "total": 0,
            "current_portal": None,
            "jobs_found": 0,
            "portals": {},
        }
        self.subscribers: List[Any] = []
        self._proc: Optional[subprocess.Popen] = None

    def cancel(self) -> bool:
        with self.lock:
            proc = self._proc
            if not self.running or proc is None:
                return False
        try:
            proc.terminate()
            return True
        except OSError as exc:
            logger.warning("Failed to terminate scanner subprocess: %s", exc)
            return False

    def subscribe(self, q: Any) -> None:
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        with self.lock:
            self.subscribers.append((q, loop))

    def unsubscribe(self, q: Any) -> None:
        with self.lock:
            self.subscribers = [
                entry for entry in self.subscribers
                if (entry[0] if isinstance(entry, tuple) else entry) is not q
            ]

    def _notify(self, event: Dict[str, Any]) -> None:
        with self.lock:
            subs = list(self.subscribers)
        for entry in subs:
            q, loop = entry if isinstance(entry, tuple) else (entry, None)
            try:
                if loop is not None and not loop.is_closed():
                    loop.call_soon_threadsafe(q.put_nowait, event)
                else:
                    q.put_nowait(event)
            except Exception as exc:
                logger.debug("Failed to notify SSE subscriber: %s", exc)

    def status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "started": self.started,
                "error": self.error,
                "summary": self.summary,
                "progress": dict(self.progress),
            }

    def start(
        self,
        priorities: Optional[List[int]] = None,
        jobage: int = 14,
        focus: str = "all",
        portals: Optional[List[str]] = None,
        region: str = "all",
        all_priorities: bool = False,
        query: Optional[str] = None,
    ) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.error = None
            self.summary = None
            self.started = datetime.now().isoformat(timespec="seconds")
            self.progress = {
                "percent": 0.0,
                "completed": 0,
                "total": 0,
                "current_portal": None,
                "jobs_found": 0,
                "portals": {},
            }

        cmd = [sys.executable, str(ROOT / "backend" / "tools" / "scrape_run.py"), "search"]
        if not (ROOT / "backend" / "tools" / "scrape_run.py").exists():
            cmd = [sys.executable, str(ROOT / "tools" / "scrape_run.py"), "search"]

        if all_priorities or not priorities:
            cmd.append("--all")
        else:
            cmd.extend(["--priority", ",".join(str(p) for p in priorities)])

        cmd.extend(["--jobage", str(jobage), "--out", str(self.out)])

        local_queries = scrape_run.active_queries_path()
        if local_queries != scrape_run.QUERIES:
            cmd.extend(["--queries", str(local_queries)])

        local_accept = scrape_run.local_target_seniority()
        if local_accept:
            cmd.extend(["--accept", ",".join(local_accept)])

        effective_focus = focus
        if portals and isinstance(portals, list):
            valid_p = [p for p in portals if p and p != "all"]
            if valid_p:
                effective_focus = ",".join(valid_p)
            elif "all" in portals:
                effective_focus = "all"
        if effective_focus and effective_focus != "all":
            cmd.extend(["--portal", effective_focus])

        if region and region != "all":
            cmd.extend(["--region", region])

        if query and query.strip():
            cmd.extend(["--query", query.strip()])

        threading.Thread(target=self._run, args=(cmd,), daemon=True).start()
        return True

    def _run(self, cmd: List[str]) -> None:
        stdout_lines = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=ROOT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            with self.lock:
                self._proc = proc

            for line in iter(proc.stdout.readline, ""):
                line_str = line.strip()
                if not line_str:
                    continue
                if line_str.startswith("PROGRESS:"):
                    try:
                        evt = json.loads(line_str[9:])
                        with self.lock:
                            self.progress["percent"] = evt.get("percent", 0.0)
                            self.progress["completed"] = evt.get("completed", 0)
                            self.progress["total"] = evt.get("total", 0)
                            self.progress["current_portal"] = evt.get("portal")
                            if evt.get("status") == "ok":
                                self.progress["jobs_found"] += evt.get("jobs", 0)
                            p_name = evt.get("portal")
                            prev = self.progress["portals"].get(p_name, {"status": "ok", "jobs": 0, "error": None})
                            add_jobs = evt.get("jobs", 0)
                            self.progress["portals"][p_name] = {
                                "status": "error" if (evt.get("status") == "error" or prev["status"] == "error") else "ok",
                                "jobs": prev["jobs"] + add_jobs,
                                "error": evt.get("error") or prev.get("error"),
                            }
                            copy_prog = dict(self.progress)
                        self._notify({"type": "progress", **copy_prog})
                    except (json.JSONDecodeError, TypeError, ValueError) as exc:
                        logger.debug("Ignoring malformed scanner PROGRESS line: %s", exc)
                else:
                    stdout_lines.append(line_str)

            proc.stdout.close()
            err = proc.stderr.read().strip()
            proc.stderr.close()
            proc.wait()

            with self.lock:
                base_sum = "\n".join(l for l in stdout_lines if not l.startswith("saved="))
                self.summary = base_sum.strip()
                self.error = (err or f"A busca terminou com erro ({proc.returncode})") if proc.returncode != 0 else None
                self.progress["percent"] = 100.0

            # Record run in database
            if self.out.exists():
                try:
                    data = json.loads(self.out.read_text(encoding="utf-8"))
                    new_jobs = data.get("new", [])
                    total_count = len(new_jobs)
                    self.repo.insert_scan_run({
                        "date": date.today().isoformat(),
                        "total_found": total_count,
                        "total_new": total_count,
                        "total_seen": 0,
                        "portals_summary": data.get("meta"),
                    })
                except (OSError, json.JSONDecodeError, sqlite3.Error) as exc:
                    logger.warning("Failed to record scan_run summary: %s", exc)
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
        finally:
            with self.lock:
                self._proc = None
                self.running = False
                copy_prog = dict(self.progress)
            self._notify({"type": "done", "status": "completed", **copy_prog})

    @staticmethod
    def _norm_text(value: Any) -> str:
        return " ".join(str(value or "").lower().split())

    @staticmethod
    def _norm_url(value: Any) -> str:
        """URL sem query string, fragmento e barra final, para comparar a mesma vaga com variações de tracking."""
        s = str(value or "").strip().lower()
        if not s:
            return ""
        s = s.split("#", 1)[0].split("?", 1)[0]
        return s.rstrip("/")

    def _load_applied_index(self) -> tuple:
        """URLs e pares (empresa, cargo) de vagas já candidatadas, vindos do ledger de candidaturas e da tabela jobs."""
        urls: set = set()
        pairs: set = set()
        if hasattr(self.repo, "get_applied_index_rows"):
            rows = self.repo.get_applied_index_rows()
        else:
            rows = []
            for sql in (
                "SELECT job_url AS url, company, role AS title FROM application_ledger",
                "SELECT url, company, title FROM jobs WHERE status = 'applied'",
            ):
                try:
                    rows.extend(dict(r) for r in self.repo.conn.execute(sql).fetchall())
                except sqlite3.Error as exc:
                    logger.debug("Legacy/mock conn query skipped in _load_applied_index: %s", exc)
        for row in rows:
            u = self._norm_url(row.get("url"))
            if u:
                urls.add(u)
            c, t = self._norm_text(row.get("company")), self._norm_text(row.get("title"))
            if c and t:
                pairs.add((c, t))
        return urls, pairs

    def _lookup_job_by_url_or_pair(self, url: str | None, company: str | None, title: str | None) -> dict | None:
        if hasattr(self.repo, "get_job_by_url"):
            row = self.repo.get_job_by_url(url) if url else None
            if row:
                return row
            if hasattr(self.repo, "get_job_by_company_title"):
                return self.repo.get_job_by_company_title(company or "", title or "")
            return None
        if url:
            cur = self.repo.conn.execute("SELECT status, fit FROM jobs WHERE url = ?", (url,))
            r = cur.fetchone()
            if r:
                return dict(r)
        if company and title:
            cur = self.repo.conn.execute(
                "SELECT status, fit FROM jobs WHERE LOWER(TRIM(company)) = LOWER(TRIM(?)) AND LOWER(TRIM(title)) = LOWER(TRIM(?))",
                (company, title),
            )
            r = cur.fetchone()
            if r:
                return dict(r)
        return None

    def load_results(self) -> Dict[str, Any]:
        """Load currently available results, filtering already-seen jobs."""
        if not self.out.exists():
            return {"meta": None, "new": []}
        try:
            data = json.loads(self.out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read scanner results %s: %s", self.out, exc)
            return {"meta": None, "new": []}

        # Filter against SQLite jobs marked as discarded or interested
        all_new = data.get("new", [])
        applied_urls, applied_pairs = self._load_applied_index()
        filtered = []
        for j in all_new:
            url = j.get("url")
            company = j.get("company")
            title = j.get("title")
            if (self._norm_url(url) in applied_urls) or (
                (self._norm_text(company), self._norm_text(title)) in applied_pairs
            ):
                continue
            row = self._lookup_job_by_url_or_pair(url, company, title)
            if row and row["status"] in ("interested", "discarded", "applied", "skipped"):
                continue
            if url:
                try:
                    scr = painel.get_cached_score(url)
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    logger.debug("Could not load cached score for %s: %s", url, exc)
                    scr = None
                if scr:
                    if isinstance(scr, dict) and scr.get("score") is not None and scr["score"] < LOW_SCORE_AUTO_DISCARD_THRESHOLD:
                        continue
                    j = {**j, "screening": scr}
            filtered.append(j)

        return {**data, "new": filtered}

    def clear_pending(self) -> int:
        if self.out.exists():
            try:
                data = json.loads(self.out.read_text(encoding="utf-8"))
                count = len(data.get("new", []))
                self.out.unlink(missing_ok=True)
                return count
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to parse pending scanner file before clearing: %s", exc)
                self.out.unlink(missing_ok=True)
        return 0

    def installed_portals(self) -> Dict[str, Any]:
        return scrape_run.installed_portals()
