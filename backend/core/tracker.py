"""Tracker service orchestrating SQLite persistence, legacy reconciliation, and enrichment."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

from backend.db.repository import Repository
from backend.tools import painel

logger = logging.getLogger(__name__)


class TrackerService:
    """Manages job tracking state, transitions, dedup, legacy sync, and applications."""

    def __init__(self, repo: Repository | None = None, db_path: str | Path | None = None):
        self.repo = repo if repo is not None else Repository(db_path)

    # ------------------------------------------------------------------
    # Primitivas SQLite (delegadas ao Repository)
    # ------------------------------------------------------------------

    def is_seen(self, url: str | None = None, company: str | None = None, title: str | None = None) -> bool:
        """Check whether a posting has already been recorded by URL or (company, title)."""
        if url and self.repo.get_job_by_url(url):
            return True
        if company and title and self.repo.get_job_by_company_title(company, title):
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

    def get_evaluation(self, job_id: str) -> dict | None:
        return self.repo.get_evaluation(job_id)

    def record_application(self, app_data: dict) -> int:
        return self.repo.upsert_application(app_data)

    def delete_application(self, app_id: int | None = None, job_id: str | None = None) -> int:
        return self.repo.delete_application(app_id=app_id, job_id=job_id)

    def get_application(self, app_id: int) -> dict | None:
        return self.repo.get_application(app_id)

    def list_applications(self, status: str | None = None) -> list[dict]:
        return self.repo.list_applications(status=status)

    def insert_application_event(self, event_data: dict) -> int:
        return self.repo.insert_application_event(event_data)

    def list_application_events(self, application_id: int | None = None) -> list[dict]:
        return self.repo.list_application_events(application_id=application_id)

    def delete_application_event(self, event_id: int) -> int:
        return self.repo.delete_application_event(event_id=event_id)

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
        return self.repo.record_application_ledger(
            company=company,
            role=role,
            portal=portal,
            job_url=job_url,
            job_id=job_id,
            applied_date=applied_date,
            applied_at=applied_at,
        )

    def archive_application_ledger(
        self,
        job_id: str | None = None,
        job_url: str | None = None,
        app_id: int | None = None,
    ) -> int:
        return self.repo.archive_application_ledger(job_id=job_id, job_url=job_url, app_id=app_id)

    def get_dashboard_stats(self, period_months: int = 6) -> dict:
        return self.repo.get_dashboard_stats(period_months=period_months)

    def get_interested_status_metadata(self, job_ids: list[str]) -> tuple[dict, dict]:
        return self.repo.get_interested_status_metadata(job_ids)

    def clear_discarded_jobs(self) -> int:
        return self.repo.clear_discarded_jobs()

    # ------------------------------------------------------------------
    # Orquestração / Reconciliação SQLite + Legacy Cache (painel.*)
    # ------------------------------------------------------------------

    @staticmethod
    def build_screening(
        item: dict[str, Any],
        cached_score: dict[str, Any] | None,
        eval_provider_map: dict[str, str],
        eval_details_map: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Build normalized screening metadata enriched with subscores, gate verdicts, and AI model."""
        screening = (
            dict(cached_score)
            if isinstance(cached_score, dict)
            else (dict(item["screening"]) if isinstance(item.get("screening"), dict) else None)
        )
        if not screening and (item.get("rank_score") is not None or item.get("rank_verdict")):
            screening = {
                "score": item.get("rank_score"),
                "verdict": item.get("rank_verdict"),
            }
        if screening is not None:
            jid = item.get("id")
            if not screening.get("ai_model") and jid and eval_provider_map.get(jid):
                screening["ai_model"] = eval_provider_map[jid]
            db_det = (eval_details_map or {}).get(jid, {}) if jid else {}
            for key in ("subscores", "location_verdict", "language_gate", "language_note", "strengths", "gaps"):
                if not screening.get(key):
                    val = db_det.get(key) or item.get(key)
                    if val:
                        screening[key] = val
        return screening

    def _merge_sqlite_and_legacy_jobs(
        self,
        status_db: str,
        legacy_loader: Callable[[], list[dict[str, Any]]],
        label: str,
    ) -> list[dict[str, Any]]:
        try:
            raw_items = self.list_jobs(status=status_db, limit=500)
        except sqlite3.Error as exc:
            logger.warning("Failed to list %s jobs from SQLite: %s", label, exc)
            raw_items = []

        if not raw_items:
            try:
                raw_items = legacy_loader()
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Failed to load legacy %s jobs: %s", label, exc)
                raw_items = []
        else:
            try:
                existing_urls = {j.get("url") for j in raw_items if j.get("url")}
                for legacy_item in legacy_loader():
                    if legacy_item.get("url") and legacy_item["url"] not in existing_urls:
                        raw_items.append(legacy_item)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Failed to merge legacy %s jobs: %s", label, exc)
        return raw_items

    def _load_eval_maps(self, job_ids: list[str], label: str) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        try:
            provider_map = self.repo.get_latest_evaluation_providers(job_ids)
        except sqlite3.Error as exc:
            logger.warning("Failed to load evaluation providers for %s jobs: %s", label, exc)
            provider_map = {}

        try:
            details_map = self.repo.get_latest_evaluation_details(job_ids)
        except sqlite3.Error as exc:
            logger.warning("Failed to load evaluation details for %s jobs: %s", label, exc)
            details_map = {}
        return provider_map, details_map

    @staticmethod
    def _safe_load_cached_score(url: str, label: str) -> dict[str, Any] | None:
        try:
            return painel.get_cached_score(url)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to load cached score for %s (%s): %s", label, url, exc)
            return None

    @staticmethod
    def _normalize_enriched_job_fields(
        item: dict[str, Any],
        screening: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workplace_type = item.get("workplace_type") or item.get("work_model")
        date_val = item.get("date") or item.get("posted_date") or item.get("first_seen")
        contract_val = item.get("contract") or item.get("contract_type")
        normalized = {
            **item,
            "workplace_type": workplace_type,
            "work_model": workplace_type,
            "date": date_val,
            "posted_date": date_val,
            "contract": contract_val,
            "contract_type": contract_val,
        }
        if screening is not None:
            normalized["screening"] = screening
        return normalized

    @staticmethod
    def _resolve_pdf_web_path(candidate: str, fallback: str | None) -> str:
        if candidate and candidate.endswith(".tex"):
            pdf_cand = candidate[:-4] + ".pdf"
            if (painel.ROOT / pdf_cand).exists():
                return pdf_cand
            if fallback:
                return fallback
        return candidate

    def list_enriched_saved_jobs(self) -> list[dict[str, Any]]:
        """List 'Me interessam' jobs merged across SQLite, legacy cache, evaluations, and PDFs."""
        raw_saved = self._merge_sqlite_and_legacy_jobs("interested", painel.saved, "saved")

        job_ids = [s.get("id") for s in raw_saved if s.get("id")]
        job_urls = [s.get("url") for s in raw_saved if s.get("url")]
        saved_at_map: dict[str, Any] = {}
        auto_meta_map: dict[str, Any] = {}
        if job_ids:
            try:
                saved_at_map, auto_meta_map = self.get_interested_status_metadata(job_ids)
            except sqlite3.Error as exc:
                logger.warning("Failed to load interested metadata: %s", exc)

        try:
            recruiter_email_map = self.repo.get_recruiter_emails_for_jobs(job_ids, job_urls)
        except sqlite3.Error as exc:
            logger.warning("Failed to load recruiter emails for saved jobs: %s", exc)
            recruiter_email_map = {}

        eval_provider_map, eval_details_map = self._load_eval_maps(job_ids, "saved")

        rows: list[dict[str, Any]] = []
        for s in raw_saved:
            u = s.get("url")
            jid = s.get("id")
            auto_meta = auto_meta_map.get(jid, {})
            rec_emails = recruiter_email_map.get(f"id:{jid}") or recruiter_email_map.get(f"url:{u}") or []
            date_val = s.get("date") or s.get("posted_date") or s.get("first_seen")
            saved_at_val = (
                saved_at_map.get(jid)
                or s.get("saved_at")
                or s.get("updated_at")
                or s.get("created_at")
                or s.get("first_seen")
                or date_val
            )
            saved_at_str = str(saved_at_val) if saved_at_val else date_val
            saved_date = saved_at_str[:10] if saved_at_str and len(saved_at_str) >= 10 else saved_at_str

            extra_meta = {
                "saved_at": saved_date,
                "saved_at_full": saved_at_str,
                "auto_promoted": bool(auto_meta.get("auto_promoted", False)),
                "auto_origin": auto_meta.get("auto_origin"),
                "auto_run_id": auto_meta.get("auto_run_id"),
                "recruiter_emails": rec_emails,
            }

            if u:
                try:
                    answers = painel.claude_answers(u)
                except OSError as exc:
                    logger.warning("Failed to load cached AI answers for %s: %s", u, exc)
                    answers = {}
                try:
                    pdfs = painel.job_pdfs(s.get("company") or "", s.get("title") or "")
                except OSError as exc:
                    logger.warning("Failed to load PDFs for %s: %s", u, exc)
                    pdfs = {}
                cached_score = self._safe_load_cached_score(u, "saved job")
                screening = self.build_screening(s, cached_score, eval_provider_map, eval_details_map)
                row = self._normalize_enriched_job_fields(s, screening=screening)
                row.update({
                    "claude": answers,
                    **pdfs,
                    **extra_meta,
                })
                rows.append(row)
            else:
                row = self._normalize_enriched_job_fields(s)
                row.update(extra_meta)
                rows.append(row)

        def sort_key(r: dict[str, Any]) -> tuple[int, str]:
            sc = r.get("screening")
            score = sc.get("score") if isinstance(sc, dict) and sc.get("score") is not None else -1
            return (score, r.get("first_seen") or r.get("date") or "")

        rows.sort(key=sort_key, reverse=True)
        return rows

    def list_enriched_discarded_jobs(self) -> list[dict[str, Any]]:
        """List discarded jobs merged across SQLite and legacy cache with AI screening."""
        raw_discarded = self._merge_sqlite_and_legacy_jobs("discarded", painel.discarded, "discarded")
        disc_ids = [d.get("id") for d in raw_discarded if d.get("id")]
        eval_provider_map, eval_details_map = self._load_eval_maps(disc_ids, "discarded")

        rows: list[dict[str, Any]] = []
        for d in raw_discarded:
            u = d.get("url")
            cached_score = self._safe_load_cached_score(u, "discarded job") if u else None
            screening = self.build_screening(d, cached_score, eval_provider_map, eval_details_map)
            rows.append(self._normalize_enriched_job_fields(d, screening=screening))

        rows.sort(key=lambda r: r.get("first_seen") or "", reverse=True)
        return rows

    def mark_decision(
        self,
        *,
        urls: list[str],
        decision: str,
        ids: list[str] | None = None,
        job_data: dict[str, Any] | None = None,
        scanner_results: dict[str, Any] | None = None,
    ) -> int:
        """Persist mark decision ('interesse'/'descartar') in SQLite and mirror to painel cache."""
        if job_data:
            job_status = (
                "interested"
                if decision in ("interesse", "interested")
                else ("discarded" if decision in ("descartar", "discarded") else decision)
            )
            fit = (
                "medium"
                if decision in ("interesse", "interested")
                else ("low" if decision in ("descartar", "discarded") else None)
            )
            self.upsert_job({**job_data, "status": job_status, "fit": fit})

        ids_to_mark = list(ids or [])
        for u in urls:
            j = self.repo.get_job_by_url(u)
            if j:
                ids_to_mark.append(j["id"])

        self.mark_jobs(ids_to_mark, decision=decision, source="painel")

        try:
            painel.mark(scanner_results, urls, decision, job_data=job_data)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to mirror mark decision in legacy painel cache: %s", exc)

        return len(urls) or len(ids_to_mark)

    def discard_by_url(self, url: str) -> bool:
        """Move a single job URL to discarded in SQLite and legacy seen_jobs."""
        job = self.repo.get_job_by_url(url)
        if job:
            self.mark_jobs([job["id"]], decision="discarded", source="painel")
        res = painel.discard_job(url)
        return bool(job or (isinstance(res, dict) and res.get("discarded")))

    def restore_by_url(self, url: str) -> None:
        """Restore a discarded job back to interested in SQLite and legacy seen_jobs."""
        job = self.repo.get_job_by_url(url)
        if job:
            self.mark_jobs([job["id"]], decision="interested", source="painel")
        painel.restore_job(url)

    def clear_discarded_with_legacy(self) -> dict[str, int]:
        """Permanently clear discarded jobs from SQLite and legacy seen_jobs.json."""
        deleted_count = self.clear_discarded_jobs()
        seen_path = painel.scrape_run.SEEN
        cleared_seen = 0
        if seen_path.exists():
            try:
                state = json.loads(seen_path.read_text(encoding="utf-8"))
                seen = state.get("seen", {})
                keys_to_remove = [
                    k
                    for k, v in seen.items()
                    if isinstance(v, dict) and (v.get("status") in ("skipped", "discarded") or v.get("fit") == "low")
                ]
                for k in keys_to_remove:
                    del seen[k]
                    cleared_seen += 1
                seen_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Failed to clear legacy discarded keys from %s: %s", seen_path, exc)
        return {"deleted_db": deleted_count, "cleared_seen": cleared_seen}

    def list_enriched_applications(self, status: str | None = None) -> list[dict[str, Any]]:
        """List applications merged across SQLite, legacy tracker.csv, recruiter context, and PDFs."""
        try:
            raw_apps = self.list_applications(status=status)
        except sqlite3.Error as exc:
            logger.warning("Failed to list applications from SQLite: %s", exc)
            raw_apps = []

        if not raw_apps:
            try:
                raw_apps = painel.applications()
            except (OSError, ValueError) as exc:
                logger.warning("Failed to read legacy applications CSV: %s", exc)
                raw_apps = []
        else:
            try:
                painel_apps = painel.applications()
                painel_by_source = {
                    p.get("source") or p.get("url"): p
                    for p in painel_apps
                    if p.get("source") or p.get("url")
                }
                existing_urls = set()
                for a in raw_apps:
                    u = a.get("job_url") or a.get("url") or a.get("source")
                    if u:
                        existing_urls.add(u)
                    if u and u in painel_by_source:
                        p = painel_by_source[u]
                        for k in ("cv_file", "cover_letter_file", "channel", "notes", "date", "role", "sector"):
                            if p.get(k) and not a.get(k):
                                a[k] = p[k]
                for p in painel_apps:
                    u = p.get("source") or p.get("url")
                    if u and u not in existing_urls:
                        raw_apps.append({
                            "job_company": p.get("company"),
                            "job_title": p.get("role"),
                            "job_url": u,
                            "job_portal": p.get("channel") or "portal",
                            "applied_date": p.get("date"),
                            "status": p.get("status") or "applied",
                            "notes": p.get("notes"),
                            "cv_file": p.get("cv_file"),
                            "cover_letter_file": p.get("cover_letter_file"),
                        })
                        existing_urls.add(u)
            except (OSError, ValueError) as exc:
                logger.warning("Failed to merge legacy tracker.csv into /applications: %s", exc)

        job_ids = [a.get("job_id") for a in raw_apps if a.get("job_id")]
        job_urls = [
            (a.get("job_url") or a.get("url") or a.get("source"))
            for a in raw_apps
            if (a.get("job_url") or a.get("url") or a.get("source"))
        ]
        try:
            recruiter_ctx_map = self.repo.get_recruiter_context_for_jobs(job_ids, job_urls)
        except sqlite3.Error as exc:
            logger.warning("Failed to resolve recruiter context for applications: %s", exc)
            recruiter_ctx_map = {}

        normalized: list[dict[str, Any]] = []
        for a in raw_apps:
            company = a.get("job_company") or a.get("company") or ""
            role = a.get("job_title") or a.get("role") or a.get("title") or ""
            url = a.get("job_url") or a.get("url") or a.get("source") or ""
            date_val = a.get("applied_date") or a.get("date") or ""
            channel_val = a.get("job_portal") or a.get("channel") or a.get("portal") or "portal"
            jid = a.get("job_id")
            ctx = recruiter_ctx_map.get(f"id:{jid}") or recruiter_ctx_map.get(f"url:{url}") or {}
            rec_emails = ctx.get("emails") or []
            contacted_email = (a.get("contacted_email") or ctx.get("contacted_email") or "").strip() or None
            contacted_at = a.get("contacted_at") or ctx.get("contacted_at")
            recruiter_post_id = a.get("recruiter_post_id") or ctx.get("post_id")
            is_direct = bool(
                contacted_email
                or a.get("contact_channel") == "recruiter_email"
                or str(url).startswith("recruiter://")
            )
            contact_channel = "recruiter_email" if is_direct else (a.get("contact_channel") or "portal")
            if is_direct and not contacted_email and rec_emails:
                contacted_email = rec_emails[0]
            job_description = a.get("job_description") or ctx.get("description") or ""

            pdfs: dict[str, Any] = {}
            if company or role:
                try:
                    pdfs = painel.job_pdfs(company, role)
                except OSError as exc:
                    logger.warning("Failed to resolve job PDFs for %s / %s: %s", company, role, exc)
                    pdfs = {}

            cv_file = self._resolve_pdf_web_path(
                a.get("cv_file") or a.get("cv_path") or pdfs.get("pdf_cv") or "",
                pdfs.get("pdf_cv"),
            )
            cover_file = self._resolve_pdf_web_path(
                a.get("cover_letter_file") or a.get("cover_letter_path") or pdfs.get("pdf_carta") or "",
                pdfs.get("pdf_carta"),
            )

            pdf_cv = pdfs.get("pdf_cv") or (cv_file if cv_file.endswith(".pdf") else None)
            pdf_carta = pdfs.get("pdf_carta") or (cover_file if cover_file.endswith(".pdf") else None)
            pdf_entrevista = pdfs.get("pdf_entrevista")
            job_posted_date = a.get("job_posted_date") or a.get("posted_date") or a.get("job_date") or ""
            applied_date_clean = date_val or (a.get("created_at") or "")[:10]

            normalized.append({
                **a,
                "company": company,
                "job_company": company,
                "role": role,
                "title": role,
                "job_title": role,
                "date": applied_date_clean,
                "applied_date": applied_date_clean,
                "job_posted_date": job_posted_date,
                "created_at": a.get("created_at") or applied_date_clean,
                "channel": channel_val,
                "portal": channel_val,
                "job_portal": channel_val,
                "url": url,
                "source": url,
                "job_url": url,
                "cv_file": cv_file,
                "cv_path": cv_file,
                "cover_letter_file": cover_file,
                "cover_letter_path": cover_file,
                "pdf_cv": pdf_cv,
                "pdf_carta": pdf_carta,
                "pdf_entrevista": pdf_entrevista,
                "recruiter_emails": rec_emails,
                "recruiter_post_id": recruiter_post_id,
                "contacted_email": contacted_email,
                "contacted_at": contacted_at,
                "contact_channel": contact_channel,
                "job_description": job_description,
            })

        return normalized

    def save_application_with_legacy(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create/update application in SQLite, ledger, and legacy tracker.csv."""
        job_id = payload.get("job_id")
        url = payload.get("url")
        title = payload.get("title")
        role = payload.get("role")
        company = payload.get("company")
        portal = payload.get("portal")

        job = None
        if not job_id and url:
            job = self.repo.get_job_by_url(url)
            if job:
                job_id = job["id"]
            elif title and company:
                job_id = self.upsert_job({
                    "title": title or role,
                    "company": company,
                    "url": url,
                    "portal": portal,
                })

        if job_id:
            self.record_application({
                "job_id": job_id,
                "status": payload.get("status"),
                "cv_path": payload.get("cv_file"),
                "cover_letter_path": payload.get("cover_letter_file"),
                "applied_date": payload.get("applied_date") or payload.get("date"),
                "notes": payload.get("notes"),
            })
            self.mark_jobs([job_id], decision="applied", source="painel")
            self.record_application_ledger(
                company=company or (job.get("company") if job else "") or "Empresa",
                role=title or role or (job.get("title") if job else "") or "Cargo",
                portal=portal or (job.get("portal") if job else "") or "portal",
                job_url=url or "",
                job_id=job_id,
                applied_date=payload.get("applied_date") or payload.get("date") or painel.date.today().isoformat(),
            )

        try:
            record = painel.save_application_record(payload)
            return {"ok": True, "record": record}
        except (OSError, ValueError) as exc:
            logger.warning("Failed to mirror application into legacy tracker.csv: %s", exc)
            if job_id:
                return {"ok": True, "warning": f"Salvo no SQLite; falha no espelho CSV legado: {exc}"}
            raise RuntimeError(f"Falha ao salvar candidatura: {exc}") from exc

    @staticmethod
    def persist_application_bundle(
        repo: Repository,
        *,
        job_id: str | None,
        url: str,
        company: str,
        role: str,
        portal: str,
        applied_date: str,
        notes: str,
        source: str,
        contact_channel: str,
        contacted_email: str | None = None,
        recruiter_post_id: int | None = None,
        contacted_at: str | None = None,
        mark_recruiter_post: bool = True,
        strict_legacy: bool = True,
    ) -> tuple[int | None, dict[str, Any]]:
        """Persist application transitions across jobs, applications, ledger, recruiter_posts, and legacy cache."""
        app_id: int | None = None
        if job_id:
            repo.mark_jobs([job_id], decision="applied", source=source, note=notes)
            app_id = repo.upsert_application({
                "job_id": job_id,
                "status": "applied",
                "applied_date": applied_date,
                "notes": notes,
                "contact_channel": contact_channel,
                "contacted_email": contacted_email,
                "recruiter_post_id": recruiter_post_id,
            })
            if mark_recruiter_post and recruiter_post_id and contacted_email and contact_channel == "recruiter_email":
                repo.mark_recruiter_post_contacted(
                    post_id=recruiter_post_id,
                    job_id=job_id,
                    contacted_email=contacted_email,
                    contacted_at=contacted_at or applied_date,
                )

        repo.record_application_ledger(
            company=company or "Empresa",
            role=role or "Cargo",
            portal=portal or "portal",
            job_url=url,
            job_id=job_id,
            applied_date=applied_date,
        )

        legacy_res: dict[str, Any] = {}
        try:
            legacy_res = painel.record_applied(
                url=url,
                company=company,
                role=role,
                portal=portal,
            )
        except (OSError, ValueError) as exc:
            if strict_legacy:
                raise
            logger.warning("Failed to mirror applied entry into legacy tracker cache (%s): %s", url, exc)
        return app_id, legacy_res

    def apply_single_job(
        self,
        *,
        url: str,
        company: str | None = None,
        role: str | None = None,
        portal: str | None = None,
        contact_channel: str | None = None,
        contacted_email: str | None = None,
    ) -> dict[str, Any]:
        """Persist a single applied job across SQLite, recruiter tracking, ledger, and legacy files."""
        job = self.repo.get_job_by_url(url)
        if not job:
            job_id = self.upsert_job({
                "title": role or "Vaga sem título",
                "company": company or "Empresa não informada",
                "url": url,
                "portal": portal or "portal",
                "status": "applied",
            })
            job = self.repo.get_job(job_id)
        else:
            updates: dict[str, Any] = {}
            if company and not job.get("company"):
                updates["company"] = company
            if role and not job.get("title"):
                updates["title"] = role
            if portal and not job.get("portal"):
                updates["portal"] = portal
            if updates:
                updates["id"] = job["id"]
                updates["url"] = job.get("url") or url
                self.upsert_job(updates)

        resolved_channel = contact_channel or "portal"
        cleaned_email = (contacted_email or "").strip().lower() or None
        recruiter_post_id = None
        if job:
            ctx_map = self.repo.get_recruiter_context_for_jobs([job["id"]], [url])
            ctx = ctx_map.get(f"id:{job['id']}") or ctx_map.get(f"url:{url}") or {}
            rec_emails = ctx.get("emails") or []
            recruiter_post_id = ctx.get("post_id")
            is_direct = bool(
                contact_channel == "recruiter_email"
                or cleaned_email
                or str(url).startswith("recruiter://")
            )
            resolved_channel = "recruiter_email" if is_direct else (contact_channel or "portal")
            if is_direct and not cleaned_email and rec_emails:
                cleaned_email = rec_emails[0].strip().lower()

        notes_val = f"E-mail direto: {cleaned_email}" if cleaned_email else "Registrado pelo painel"
        company_name = company or (job.get("company") if job else "") or ""
        role_title = role or (job.get("title") if job else "") or ""
        portal_name = portal or (job.get("portal") if job else "") or ""

        _, legacy_res = self.persist_application_bundle(
            self.repo,
            job_id=job["id"] if job else None,
            url=url,
            company=company_name,
            role=role_title,
            portal=portal_name,
            applied_date=painel.date.today().isoformat(),
            notes=notes_val,
            source="painel",
            contact_channel=resolved_channel,
            contacted_email=cleaned_email,
            recruiter_post_id=recruiter_post_id,
            contacted_at=painel.date.today().isoformat(),
            strict_legacy=True,
        )
        return legacy_res

    def remove_application_with_legacy(
        self,
        *,
        app_id: int | None = None,
        job_id: str | None = None,
        url: str | None = None,
    ) -> str:
        """Remove application from SQLite and legacy CSV while archiving ledger history."""
        target_job_id = job_id
        url_to_clean = (url or "").strip()

        if app_id:
            app_row = self.repo.get_application(app_id)
            if app_row:
                target_job_id = target_job_id or app_row.get("job_id")
            self.repo.delete_application(app_id=app_id)

        if not target_job_id and url_to_clean:
            job = self.repo.get_job_by_url(url_to_clean)
            if job:
                target_job_id = job["id"]

        if target_job_id:
            if not url_to_clean:
                job = self.repo.get_job(target_job_id)
                if job:
                    url_to_clean = job.get("url") or ""
            self.repo.delete_application(job_id=target_job_id)
            self.mark_jobs([target_job_id], decision="discarded", source="painel")

        self.archive_application_ledger(
            job_id=target_job_id,
            job_url=url_to_clean,
            app_id=app_id,
        )
        if url_to_clean:
            painel.remove_application(url_to_clean)
        return url_to_clean

    def reopen_recruiter_with_legacy(
        self,
        *,
        app_id: int | None = None,
        job_id: str | None = None,
        url: str | None = None,
        recruiter_post_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Reopen recruiter outreach in SQLite and remove legacy CSV entry."""
        reopened = self.repo.reopen_recruiter_post_from_application(
            app_id=app_id,
            job_id=job_id,
            job_url=url,
            recruiter_post_id=recruiter_post_id,
        )
        if not reopened:
            return None

        url_to_clean = reopened.get("url") or (url or "").strip()
        if url_to_clean:
            try:
                painel.remove_application(url_to_clean)
            except OSError as exc:
                logger.warning("Failed to remove legacy CSV application %s: %s", url_to_clean, exc)
        return reopened

    def add_application_event_with_status(
        self,
        *,
        application_id: int | None = None,
        job_id: str | None = None,
        url: str | None = None,
        stage: str,
        event_date: str | None = None,
        feedback: str | None = None,
        questions_and_answers: str | None = None,
        status_update: str | None = None,
    ) -> int | None:
        """Resolve target application ID, insert timeline event, and propagate status update."""
        app_id = application_id
        if not app_id:
            target_job_id = job_id
            if not target_job_id and url:
                job = self.repo.get_job_by_url(url)
                if job:
                    target_job_id = job["id"]
            if target_job_id:
                for a in self.list_applications():
                    if a.get("job_id") == target_job_id:
                        app_id = a.get("id")
                        break

        if not app_id:
            return None

        event_id = self.insert_application_event({
            "application_id": app_id,
            "stage": stage,
            "event_date": event_date or painel.date.today().isoformat(),
            "feedback": feedback or "",
            "questions_and_answers": questions_and_answers or "",
        })

        if status_update and status_update in painel.APPLICATION_STATUSES:
            app_row = self.get_application(app_id)
            self.record_application({"id": app_id, "status": status_update})
            if app_row and app_row.get("job_id"):
                self.mark_jobs([app_row["job_id"]], decision=status_update, source="painel")

        return event_id
