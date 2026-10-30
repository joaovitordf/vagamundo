"""Evaluator service orchestrating job evaluation and scoring."""

from __future__ import annotations
import asyncio
from datetime import date
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.db.repository import Repository
from backend.tools import painel, painel_ia


class EvaluatorService:
    """Manages AI-driven scoring, dimensions evaluation, and batch ranking."""

    def __init__(self, repo: Optional[Repository] = None):
        self.repo = repo or Repository()
        self._batch_lock = threading.Lock()
        self.batch: Dict[str, Any] = {
            "running": False,
            "current": 0,
            "total": 0,
            "percent": 0.0,
            "current_title": "",
            "errors": 0,
            "high_fit": 0,
            "med_fit": 0,
            "low_fit": 0,
            "provider": "",
            "results": {},
        }

    @staticmethod
    def parse_report(md: str) -> Dict[str, Any]:
        """Extract global score and verdict from the markdown evaluation report."""
        score_m = re.search(r"Nota geral:\s*\**\s*(\d{1,3})\s*/\s*100", md or "")
        verdict_m = re.search(r"Veredito:\s*\[?([A-Za-z ]+?)\]?\s*$", md or "", re.M)
        return {
            "score": int(score_m.group(1)) if score_m else None,
            "verdict": verdict_m.group(1).strip() if verdict_m else None,
        }

    def _persist(self, url: str, job_data: Optional[Dict[str, Any]], score: Optional[int],
                 verdict: Optional[str], report: str, provider: str = "antigravity") -> Optional[Any]:
        job = self.repo.get_job_by_url(url)
        job_id = job["id"] if job else None
        if not job_id and job_data:
            try:
                job_id = self.repo.upsert_job(job_data)
            except Exception:
                pass
        if job_id:
            try:
                self.repo.insert_evaluation({
                    "job_id": job_id,
                    "score_global": score,
                    "verdict": verdict,
                    "strengths": [],
                    "gaps": [],
                    "report_md": report,
                    "ai_provider": provider,
                })
            except Exception:
                pass
        return job_id

    async def evaluate_job(self, url: str, job_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Detailed evaluation of a single job posting against the candidate profile."""
        def _run() -> Dict[str, Any]:
            md_report = painel_ia.avaliar_vaga(url)
            parsed = self.parse_report(md_report)
            job_id = self._persist(url, job_data, parsed["score"], parsed["verdict"], md_report)
            return {"url": url, "job_id": job_id, "report": md_report, "parsed": parsed}

        return await asyncio.to_thread(_run)

    def _load_jobs_map(self) -> Dict[str, Any]:
        jobs_map: Dict[str, Any] = {}
        try:
            from backend.core.scanner import default_results_path
            p = default_results_path()
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                for j in data.get("new", []) + data.get("jobs", []):
                    if isinstance(j, dict) and j.get("url"):
                        jobs_map[j["url"]] = j
        except Exception:
            pass
        return jobs_map

    def batch_status(self) -> Dict[str, Any]:
        with self._batch_lock:
            return {
                "running": self.batch["running"],
                "current": self.batch["current"],
                "total": self.batch["total"],
                "percent": self.batch.get("percent", 0.0),
                "current_title": self.batch.get("current_title", ""),
                "errors": self.batch.get("errors", 0),
                "high_fit": self.batch.get("high_fit", 0),
                "med_fit": self.batch.get("med_fit", 0),
                "low_fit": self.batch.get("low_fit", 0),
                "provider": self.batch.get("provider", ""),
                "results": dict(self.batch.get("results", {})),
            }

    def _screen_one(self, url: str, jobs_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        jobs_map = jobs_map or {}
        job = jobs_map.get(url) or self.repo.get_job_by_url(url)
        job_title = (job.get("title") if job else "") or "Vaga"
        company = (job.get("company") if job else "")
        disp = f"{job_title} ({company})" if company else job_title

        with self._batch_lock:
            self.batch["current_title"] = disp[:80]

        try:
            res = painel_ia.triar_vaga_rapida(url, job)
            score = res.get("score")
            verdict = res.get("verdict")
            summary = res.get("summary") or ""
            job_id = self._persist(url, job, score, verdict, summary)

            # Se a nota for estritamente baixa (< 40), descarta automaticamente
            if isinstance(score, (int, float)) and score < 40:
                res["discarded"] = True
                # 1. Atualizar banco SQLite com status = 'discarded' e fit = 'low'
                if job_id:
                    try:
                        self.repo.mark_jobs(
                            [job_id],
                            decision="descartar",
                            source="ai_triage",
                            note=f"Auto-descartada por nota baixa na triagem ({score}/100)",
                        )
                        with self.repo.conn:
                            self.repo.conn.execute(
                                "UPDATE jobs SET rank_score = ?, rank_verdict = ?, rank_date = ? WHERE id = ?",
                                (int(score), verdict, date.today().isoformat(), job_id),
                            )
                    except Exception:
                        pass

                # 2. Atualizar seen_jobs.json e painel
                try:
                    from backend.core.scanner import default_results_path
                    p = default_results_path()
                    if p.exists():
                        data = json.loads(p.read_text(encoding="utf-8"))
                        painel.mark(data, [url], "descartar", job_data=job)
                    else:
                        painel.mark(None, [url], "descartar", job_data=job)
                except Exception:
                    pass
            elif job_id and isinstance(score, (int, float)):
                # Se nota >= 40, persiste rank_score e rank_verdict para ordenação
                try:
                    with self.repo.conn:
                        self.repo.conn.execute(
                            "UPDATE jobs SET rank_score = ?, rank_verdict = ?, rank_date = ? WHERE id = ?",
                            (int(score), verdict, date.today().isoformat(), job_id),
                        )
                except Exception:
                    pass

            with self._batch_lock:
                self.batch["current"] += 1
                tot = max(1, self.batch["total"])
                self.batch["percent"] = round((self.batch["current"] / tot) * 100, 1)
                if isinstance(score, (int, float)):
                    if score >= 75:
                        self.batch["high_fit"] += 1
                    elif score >= 50:
                        self.batch["med_fit"] += 1
                    else:
                        self.batch["low_fit"] += 1
                self.batch["results"][url] = res
            return {**res, "ok": True}
        except Exception as exc:
            with self._batch_lock:
                self.batch["current"] += 1
                tot = max(1, self.batch["total"])
                self.batch["percent"] = round((self.batch["current"] / tot) * 100, 1)
                self.batch["errors"] += 1
                self.batch["results"][url] = {"url": url, "error": str(exc)[:300], "score": None}
            return {"url": url, "ok": False, "error": str(exc)[:300]}

    def start_batch(self, urls: List[str], workers: int = 2) -> bool:
        """Screen jobs in a background thread; progress is exposed via batch_status()."""
        # Deduplicate and validate
        valid_urls = [u for u in dict.fromkeys(urls) if str(u).startswith("http")]
        if not valid_urls:
            return False

        with self._batch_lock:
            if self.batch["running"]:
                return False

            provider_info = painel_ia.get_provider_info()
            provider_label = provider_info.get("label", "Google Gemini (Antigravity (agy))")

            self.batch = {
                "running": True,
                "current": 0,
                "total": len(valid_urls),
                "percent": 0.0,
                "current_title": "Iniciando IA do Antigravity...",
                "errors": 0,
                "high_fit": 0,
                "med_fit": 0,
                "low_fit": 0,
                "provider": provider_label,
                "results": {},
            }

        jobs_map = self._load_jobs_map()

        def _worker() -> None:
            try:
                with ThreadPoolExecutor(max(1, workers)) as ex:
                    # Execute all in pool
                    list(ex.map(lambda u: self._screen_one(u, jobs_map), valid_urls))
            finally:
                with self._batch_lock:
                    self.batch["running"] = False
                    self.batch["percent"] = 100.0

        threading.Thread(target=_worker, daemon=True).start()
        return True
