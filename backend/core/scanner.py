"""Scanner service coordinating portal job searches with real-time progress streaming."""

from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.db.repository import Repository
from backend.tools import painel, scrape_run

_here = Path(__file__).resolve()
ROOT = _here.parent.parent.parent if _here.parent.parent.name == "backend" else _here.parent.parent


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

    def subscribe(self, q: Any) -> None:
        with self.lock:
            self.subscribers.append(q)

    def unsubscribe(self, q: Any) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def _notify(self, event: Dict[str, Any]) -> None:
        with self.lock:
            subs = list(self.subscribers)
        for s in subs:
            try:
                s.put_nowait(event)
            except Exception:
                pass

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

        threading.Thread(target=self._run, args=(cmd, focus), daemon=True).start()
        return True

    def _run(self, cmd: List[str], focus: str = "all") -> None:
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
                    except Exception:
                        pass
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
                except Exception:
                    pass
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
        finally:
            with self.lock:
                self.running = False
                copy_prog = dict(self.progress)
            self._notify({"type": "done", "status": "completed", **copy_prog})

    def load_results(self) -> Dict[str, Any]:
        """Load currently available results, filtering already-seen jobs."""
        if not self.out.exists():
            return {"meta": None, "new": []}
        try:
            data = json.loads(self.out.read_text(encoding="utf-8"))
        except Exception:
            return {"meta": None, "new": []}

        # Filter against SQLite jobs marked as discarded or interested
        all_new = data.get("new", [])
        filtered = []
        for j in all_new:
            url = j.get("url")
            company = j.get("company")
            title = j.get("title")
            cur = self.repo.conn.execute(
                "SELECT id, status, fit FROM jobs WHERE url = ? OR (LOWER(TRIM(company)) = LOWER(TRIM(?)) AND LOWER(TRIM(title)) = LOWER(TRIM(?)))",
                (url, company or "", title or ""),
            )
            row = cur.fetchone()
            if row and row["status"] in ("interested", "discarded", "applied", "skipped"):
                continue
            if url:
                try:
                    scr = painel.get_cached_score(url)
                except Exception:
                    scr = None
                if scr:
                    if isinstance(scr, dict) and scr.get("score") is not None and scr["score"] < 40:
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
            except Exception:
                self.out.unlink(missing_ok=True)
        return 0

    def installed_portals(self) -> Dict[str, Any]:
        return scrape_run.installed_portals()
