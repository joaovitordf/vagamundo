"""Evaluator service orchestrating job evaluation and scoring."""

from __future__ import annotations
import asyncio
import json
import logging
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from backend.core.constants import (
    HIGH_FIT_MIN_SCORE,
    LOW_SCORE_AUTO_DISCARD_THRESHOLD,
    MED_FIT_MIN_SCORE,
)
from backend.db.repository import Repository
from backend.tools import painel, painel_ia, rank_state

logger = logging.getLogger(__name__)


class EvaluatorService:
    """Manages AI-driven scoring, dimensions evaluation, and batch ranking."""

    def __init__(self, repo: Optional[Repository] = None):
        self.repo = repo or Repository()
        self._batch_lock = threading.Lock()
        self._reeval_lock = threading.Lock()
        self._db_lock = threading.Lock()
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
            "auto_interested": 0,
            "promoted_items": [],
            "provider": "",
            "results": {},
        }
        self.reeval_batch: Dict[str, Any] = {
            "running": False,
            "current": 0,
            "total": 0,
            "percent": 0.0,
            "current_title": "",
            "errors": 0,
            "provider": "",
            "results": {},
        }

    @staticmethod
    def parse_report(md: str) -> Dict[str, Any]:
        """Extract global score, verdict, and optional AI model header from the markdown evaluation report."""
        score_m = re.search(r"Nota geral:\s*\**\s*(\d{1,3})\s*/\s*100", md or "")
        verdict_m = re.search(r"Veredito:\s*\**\s*\[?([A-Za-zÀ-ÿ ]+?)\]?\s*\**\s*$", md or "", re.M)
        model_m = re.search(r"Modelo(?:\s+IA)?\s*[:=]\s*[*`]*\s*([^\n*`]+)", md or "", re.IGNORECASE)
        return {
            "score": int(score_m.group(1)) if score_m else None,
            "verdict": verdict_m.group(1).strip(" *[]") if verdict_m else None,
            "ai_model": model_m.group(1).strip(" *`") if model_m else None,
        }

    @staticmethod
    def parse_report_details(md: str) -> Dict[str, Any]:
        """Extract structured subscores, gate verdicts, strengths, and gaps from Markdown."""
        return painel_ia.extract_eval_details_from_md(md)

    def _resolve_job_data(
        self,
        url: str,
        job_data: Optional[Dict[str, Any]] = None,
        jobs_map: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve stored job metadata and recruiter description for reliable evaluation."""
        with self._db_lock:
            db_job = self.repo.get_job_by_url(url)
            merged: Dict[str, Any] = {}
            for src in ((jobs_map or {}).get(url), db_job, job_data):
                if isinstance(src, dict):
                    merged.update({k: v for k, v in src.items() if v is not None and v != ""})

            if url and not merged.get("description"):
                jid = merged.get("id")
                try:
                    rec = self.repo.get_latest_recruiter_post_for_job(jid, url)
                    if rec:
                        for col in ("description", "title", "company", "location", "work_model"):
                            if rec.get(col) and not merged.get(col):
                                merged[col] = rec[col]
                except sqlite3.Error as exc:
                    logger.warning("Failed to resolve recruiter description for %s: %s", url, exc)

        return merged or None

    @staticmethod
    def _write_evaluation_file(url: str, report_md: str) -> None:
        """Persist full Markdown evaluation cache so /api/saved and document generators see it."""
        if not url or not report_md:
            return
        try:
            eval_file = painel.claude_file(url, "avaliar", base=painel.CLAUDE_DIR)
            eval_file.parent.mkdir(parents=True, exist_ok=True)
            eval_file.write_text(report_md.rstrip() + "\n", encoding="utf-8")
        except OSError:
            pass

    def _evaluate_one_sync(
        self,
        url: str,
        job_data: Optional[Dict[str, Any]] = None,
        jobs_map: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run full AI evaluation for one job and update SQLite + cached markdown without altering status."""
        resolved = self._resolve_job_data(url, job_data=job_data, jobs_map=jobs_map)
        md_report = painel_ia.avaliar_vaga(url, job_data=resolved)
        parsed = self.parse_report(md_report)
        details = self.parse_report_details(md_report)
        if parsed.get("score") is not None and not parsed.get("verdict"):
            parsed["verdict"] = rank_state.band(parsed["score"])
        ai_model = parsed.get("ai_model") or painel_ia.get_active_model_name()

        self._write_evaluation_file(url, md_report)
        with self._db_lock:
            job_id = self._persist(
                url,
                resolved,
                parsed["score"],
                parsed["verdict"],
                md_report,
                provider=ai_model,
                details=details,
            )
            if job_id and parsed["score"] is not None:
                self._update_rank_fields(job_id, parsed["score"], parsed["verdict"], details=details)

        return {
            "url": url,
            "job_id": job_id,
            "report": md_report,
            "parsed": parsed,
            "details": details,
            "ai_model": ai_model,
        }

    def _persist(
        self,
        url: str,
        job_data: Optional[Dict[str, Any]],
        score: Optional[int],
        verdict: Optional[str],
        report: str,
        provider: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        job = self.repo.get_job_by_url(url)
        job_id = job["id"] if job else None
        payload = job_data or ({"url": url, "title": "Vaga", "status": "new"} if url else None)
        if not job_id and payload:
            try:
                job_id = self.repo.upsert_job(payload)
            except (sqlite3.Error, ValueError) as exc:
                logger.warning("Failed to upsert job before evaluation persist (%s): %s", url, exc)
        if job_id:
            det = details if isinstance(details, dict) else {}
            subs = det.get("subscores") if isinstance(det.get("subscores"), dict) else {}
            try:
                self.repo.insert_evaluation({
                    "job_id": job_id,
                    "score_technical": subs.get("technical"),
                    "score_experience": subs.get("experience"),
                    "score_behavioral": subs.get("behavioral"),
                    "score_location": det.get("location_verdict"),
                    "score_career": subs.get("career"),
                    "score_global": score,
                    "verdict": verdict,
                    "language_gate": det.get("language_gate"),
                    "language_note": det.get("language_note"),
                    "strengths": det.get("strengths") or [],
                    "gaps": det.get("gaps") or [],
                    "report_md": report,
                    "ai_provider": provider or painel_ia.get_active_model_name(),
                })
            except sqlite3.Error as exc:
                logger.warning("Failed to persist evaluation for job %s: %s", job_id, exc)
        return job_id

    async def evaluate_job(self, url: str, job_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Detailed evaluation of a single job posting against the candidate profile."""
        return await asyncio.to_thread(self._evaluate_one_sync, url, job_data)

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
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.debug("Could not load scanner results map for evaluation: %s", exc)
        return jobs_map

    @staticmethod
    def _active_provider_label() -> str:
        provider_info = painel_ia.get_provider_info()
        return provider_info.get("label") or painel_ia.get_active_model_name()

    @staticmethod
    def _snapshot_batch_state(lock: threading.Lock, state: Dict[str, Any], *, include_fit: bool) -> Dict[str, Any]:
        with lock:
            snap: Dict[str, Any] = {
                "running": state["running"],
                "current": state["current"],
                "total": state["total"],
                "percent": state.get("percent", 0.0),
                "current_title": state.get("current_title", ""),
                "errors": state.get("errors", 0),
                "provider": state.get("provider", ""),
                "results": dict(state.get("results", {})),
            }
            if include_fit:
                snap.update({
                    "high_fit": state.get("high_fit", 0),
                    "med_fit": state.get("med_fit", 0),
                    "low_fit": state.get("low_fit", 0),
                    "auto_interested": state.get("auto_interested", 0),
                    "promoted_items": list(state.get("promoted_items", [])),
                })
            return snap

    def batch_status(self) -> Dict[str, Any]:
        return self._snapshot_batch_state(self._batch_lock, self.batch, include_fit=True)

    def _update_rank_fields(
        self,
        job_id: str,
        score: float,
        verdict: Optional[str],
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            self.repo.update_job_ranking(job_id, score, verdict, details=details)
        except sqlite3.Error as exc:
            logger.warning("Failed to update ranking fields for job %s: %s", job_id, exc)

    @staticmethod
    def _sync_painel_mark(url: str, decision: str, job_data: Optional[Dict[str, Any]]) -> None:
        try:
            from backend.core.scanner import default_results_path
            p = default_results_path()
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
            painel.mark(data, [url], decision, job_data=job_data)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to mirror painel decision for %s: %s", url, exc)

    def _screen_one(
        self,
        url: str,
        jobs_map: Optional[Dict[str, Any]] = None,
        auto_interest_min: Optional[int] = None,
        run_id: Optional[str] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        if should_stop and should_stop():
            return {"url": url, "ok": False, "skipped": True}

        jobs_map = jobs_map or {}
        with self._db_lock:
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
            ai_model = res.get("ai_model") or painel_ia.get_active_model_name()
            details = {
                k: res.get(k)
                for k in ("subscores", "location_verdict", "language_gate", "language_note", "strengths", "gaps")
                if res.get(k)
            }

            promoted = False
            with self._db_lock:
                job_id = self._persist(url, job, score, verdict, summary, provider=ai_model, details=details)

                # Se a nota for estritamente baixa (< LOW_SCORE_AUTO_DISCARD_THRESHOLD), descarta automaticamente
                if isinstance(score, (int, float)) and score < LOW_SCORE_AUTO_DISCARD_THRESHOLD:
                    res["discarded"] = True
                    if job_id:
                        try:
                            self.repo.mark_jobs(
                                [job_id],
                                decision="descartar",
                                source="ai_triage",
                                note=f"Auto-descartada por nota baixa na triagem ({score}/100)",
                            )
                            self._update_rank_fields(job_id, score, verdict, details=details)
                        except sqlite3.Error as exc:
                            logger.warning("Failed to auto-discard low-score job %s: %s", job_id, exc)
                    self._sync_painel_mark(url, "descartar", job)
                elif auto_interest_min is not None and isinstance(score, (int, float)) and score >= auto_interest_min:
                    if job_id:
                        existing = self.repo.get_job(job_id) or self.repo.get_job_by_url(url)
                        curr_status = existing["status"] if existing else None
                        if curr_status not in ("applied", "discarded", "skipped", "interested"):
                            note_prefix = f"[auto:{run_id}] " if run_id else ""
                            self.repo.mark_jobs(
                                [job_id],
                                decision="interested",
                                source="auto_triage",
                                note=f"{note_prefix}Auto-interesse por nota na triagem ({int(score)}/100)",
                            )
                            self._update_rank_fields(job_id, score, verdict, details=details)
                            self._sync_painel_mark(url, "interesse", job)
                            res["auto_interested"] = True
                            promoted = True
                elif job_id and isinstance(score, (int, float)):
                    # Persiste rank_score e rank_verdict para ordenação
                    self._update_rank_fields(job_id, score, verdict, details=details)

            with self._batch_lock:
                self.batch["current"] += 1
                tot = max(1, self.batch["total"])
                self.batch["percent"] = round((self.batch["current"] / tot) * 100, 1)
                if isinstance(score, (int, float)):
                    if score >= HIGH_FIT_MIN_SCORE:
                        self.batch["high_fit"] += 1
                    elif score >= MED_FIT_MIN_SCORE:
                        self.batch["med_fit"] += 1
                    else:
                        self.batch["low_fit"] += 1
                if promoted:
                    self.batch["auto_interested"] += 1
                    self.batch["promoted_items"].append({
                        "url": url,
                        "job_id": job_id,
                        "title": job_title,
                        "company": company or "",
                        "score": int(score),
                        "verdict": verdict,
                        "summary": summary,
                        "ai_model": ai_model,
                    })
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

    def _run_pool_job(
        self,
        *,
        valid_urls: List[str],
        lock: threading.Lock,
        state: Dict[str, Any],
        item_fn: Callable[[str], Any],
        workers: int,
        blocking: bool,
    ) -> None:
        def _worker() -> None:
            try:
                with ThreadPoolExecutor(max(1, workers)) as ex:
                    list(ex.map(item_fn, valid_urls))
            finally:
                with lock:
                    state["running"] = False
                    state["percent"] = 100.0

        if blocking:
            _worker()
        else:
            threading.Thread(target=_worker, daemon=True).start()

    def start_batch(
        self,
        urls: List[str],
        workers: int = 2,
        auto_interest_min: Optional[int] = None,
        run_id: Optional[str] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        blocking: bool = False,
        extra_jobs: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Screen jobs in a background thread (or blocking when awaited by orchestrator)."""
        valid_urls = [u for u in dict.fromkeys(urls) if str(u).startswith("http")]
        if not valid_urls:
            return False

        with self._batch_lock:
            if self.batch["running"]:
                return False

            self.batch = {
                "running": True,
                "current": 0,
                "total": len(valid_urls),
                "percent": 0.0,
                "current_title": "Iniciando IA...",
                "errors": 0,
                "high_fit": 0,
                "med_fit": 0,
                "low_fit": 0,
                "auto_interested": 0,
                "promoted_items": [],
                "provider": self._active_provider_label(),
                "results": {},
            }

        jobs_map = self._load_jobs_map()
        if extra_jobs:
            jobs_map.update(extra_jobs)

        self._run_pool_job(
            valid_urls=valid_urls,
            lock=self._batch_lock,
            state=self.batch,
            item_fn=lambda u: self._screen_one(
                u,
                jobs_map,
                auto_interest_min=auto_interest_min,
                run_id=run_id,
                should_stop=should_stop,
            ),
            workers=workers,
            blocking=blocking,
        )
        return True

    def reeval_status(self) -> Dict[str, Any]:
        """Return isolated batch re-evaluation status for the Me Interessam tab."""
        return self._snapshot_batch_state(self._reeval_lock, self.reeval_batch, include_fit=False)

    def _reevaluate_one(self, url: str, jobs_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resolved = self._resolve_job_data(url, jobs_map=jobs_map)
        job_title = (resolved.get("title") if resolved else "") or "Vaga"
        company = (resolved.get("company") if resolved else "") or ""
        disp = f"{job_title} ({company})" if company else job_title
        with self._reeval_lock:
            self.reeval_batch["current_title"] = disp[:80]

        try:
            res = self._evaluate_one_sync(url, job_data=resolved, jobs_map=jobs_map)
            parsed = res.get("parsed") or {}
            details = res.get("details") or {}
            entry = {
                "url": url,
                "ok": True,
                "score": parsed.get("score"),
                "verdict": parsed.get("verdict"),
                "ai_model": res.get("ai_model"),
                **({k: details[k] for k in ("subscores", "location_verdict", "language_gate", "language_note") if details.get(k)}),
            }
            with self._reeval_lock:
                self.reeval_batch["current"] += 1
                tot = max(1, self.reeval_batch["total"])
                self.reeval_batch["percent"] = round((self.reeval_batch["current"] / tot) * 100, 1)
                self.reeval_batch["results"][url] = entry
            return entry
        except Exception as exc:
            entry = {"url": url, "ok": False, "error": str(exc)[:300], "score": None}
            with self._reeval_lock:
                self.reeval_batch["current"] += 1
                tot = max(1, self.reeval_batch["total"])
                self.reeval_batch["percent"] = round((self.reeval_batch["current"] / tot) * 100, 1)
                self.reeval_batch["errors"] += 1
                self.reeval_batch["results"][url] = entry
            return entry

    def start_reevaluate_batch(
        self,
        urls: List[str],
        workers: int = 2,
        blocking: bool = False,
    ) -> bool:
        """Re-evaluate saved jobs in background without modifying status or auto-discarding."""
        valid_urls = [
            u for u in dict.fromkeys(urls)
            if isinstance(u, str) and u.startswith(("http://", "https://", "recruiter://"))
        ]
        if not valid_urls:
            return False

        with self._reeval_lock:
            if self.reeval_batch["running"]:
                return False

            self.reeval_batch = {
                "running": True,
                "current": 0,
                "total": len(valid_urls),
                "percent": 0.0,
                "current_title": "Iniciando reavaliação com IA...",
                "errors": 0,
                "provider": self._active_provider_label(),
                "results": {},
            }

        jobs_map = self._load_jobs_map()
        self._run_pool_job(
            valid_urls=valid_urls,
            lock=self._reeval_lock,
            state=self.reeval_batch,
            item_fn=lambda u: self._reevaluate_one(u, jobs_map),
            workers=workers,
            blocking=blocking,
        )
        return True
