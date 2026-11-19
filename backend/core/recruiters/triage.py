"""AI triage, candidate diversification, job promotion, and outreach transition helpers."""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.core.constants import APPLIED_PIPELINE_STATUSES, EXCLUDED_RADAR_JOB_STATUSES
from backend.core.recruiters.parser import (
    PORTAL_PRIORITY,
    strip_accents,
    tokenize_search_keywords,
)
from backend.db import RepositoryError
from backend.tools import ai_providers, painel_ia

logger = logging.getLogger(__name__)


def _facade_ai_providers() -> Any:
    mod = sys.modules.get("backend.core.recruiter_service")
    return getattr(mod, "ai_providers", ai_providers) if mod is not None else ai_providers


class RecruiterTriageMixin:
    """AI triage, promotion to Me Interessam, direct outreach recording, and dismissal."""

    def find_untriaged_candidates(
        self,
        keywords: Optional[List[str]] = None,
        include_urls: Optional[Set[str]] = None,
        max_per_email: int = 2,
        include_portals: Tuple[str, ...] = (),
        include_post_ids: Optional[Set[int]] = None,
        max_extra_portal_posts: int = 25,
    ) -> List[dict]:
        """Return untriaged active posts matching keywords/URLs, explicit imported IDs, or portals with email diversity."""
        all_untriaged = self.repo.list_recruiter_posts(only_untriaged=True)
        norm_kws = tokenize_search_keywords(keywords)
        extra_urls = {str(u).strip() for u in (include_urls or set()) if str(u or "").strip()}
        extra_ids = {int(pid) for pid in (include_post_ids or set()) if pid is not None}
        portal_set = {str(p).strip() for p in (include_portals or ()) if str(p or "").strip()}

        if not norm_kws and not extra_urls and not extra_ids:
            matched = list(all_untriaged)
        else:
            matched = []
            extra_portal_pool: List[dict] = []
            for post in all_untriaged:
                p_id = post.get("id")
                if p_id is not None and int(p_id) in extra_ids:
                    matched.append(post)
                    continue
                p_url = str(post.get("url") or "").strip()
                if p_url and p_url in extra_urls:
                    matched.append(post)
                    continue
                hay = strip_accents(
                    f"{post.get('title') or ''} {post.get('company') or ''} "
                    f"{post.get('description') or ''} {' '.join(post.get('matched_keywords') or [])}"
                )
                if any(kw in hay for kw in norm_kws):
                    matched.append(post)
                elif portal_set and str(post.get("portal") or "") in portal_set:
                    extra_portal_pool.append(post)

            if extra_portal_pool and max_extra_portal_posts > 0:
                extra_portal_pool.sort(
                    key=lambda p: (
                        int(p.get("match_score") or 0),
                        str(p.get("published_date") or ""),
                        int(p.get("id") or 0),
                    ),
                    reverse=True,
                )
                matched.extend(extra_portal_pool[:max_extra_portal_posts])

        matched.sort(
            key=lambda p: (
                PORTAL_PRIORITY.get(str(p.get("portal") or ""), 2),
                int(p.get("match_score") or 0),
                str(p.get("published_date") or ""),
            ),
            reverse=True,
        )
        if max_per_email <= 0:
            return matched

        diversified: List[dict] = []
        email_counts: Dict[str, int] = {}
        for post in matched:
            emails = [str(e).strip().lower() for e in (post.get("emails") or []) if str(e).strip()]
            primary = emails[0] if emails else ""
            if primary:
                if email_counts.get(primary, 0) >= max_per_email:
                    continue
                email_counts[primary] = email_counts.get(primary, 0) + 1
            diversified.append(post)
        return diversified

    def _prepare_job_from_post(
        self,
        post: dict,
        score: Optional[int] = None,
        verdict: Optional[str] = None,
        best_email: str = "",
        existing: Optional[dict] = None,
    ) -> Tuple[str, str, dict]:
        """Ensure a jobs row and local cache exist for a recruiter post without calling LLMs."""
        post_id = post["id"]
        raw_url = str(post.get("url") or "").strip()
        job_url = (existing.get("url") if existing else None) or raw_url or f"recruiter://post/{post_id}"

        desc_text = str(post.get("description") or "").strip()
        if best_email and best_email.lower() not in desc_text.lower():
            desc_text = f"Contato direto: {best_email}\n\n{desc_text}".strip()

        job_payload: dict = {
            "id": existing["id"] if existing else None,
            "title": post.get("title") or "Oportunidade",
            "company": post.get("company") or "Empresa",
            "url": job_url,
            "location": post.get("location"),
            "portal": post.get("portal") or "recruiter_radar",
            "work_model": post.get("work_model"),
            "posted_date": post.get("published_date"),
            "description": desc_text,
        }
        if score is not None:
            job_payload["rank_score"] = int(score)
        if verdict:
            job_payload["rank_verdict"] = verdict
        if score is not None or verdict:
            job_payload["rank_date"] = date.today().isoformat()

        if existing:
            jid = existing["id"]
            if score is not None or verdict:
                self.repo.update_job_ranking(jid, score, verdict)
            self.repo.fill_missing_job_metadata(jid, job_payload)
            for field in ("location", "work_model", "posted_date", "description", "portal"):
                job_payload[field] = (existing.get(field) or "").strip() or job_payload.get(field)
        else:
            jid = self.repo.upsert_job({**job_payload, "source": "recruiter_radar", "status": "new"})

        try:
            painel_ia.save_job_cache(job_url, {**job_payload, "id": jid})
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to cache recruiter job %s: %s", job_url, exc)

        return jid, job_url, job_payload

    def _find_existing_job_for_post(self, post: dict) -> Optional[dict]:
        """Locate existing jobs row linked by job_id or URL/synthetic recruiter URI."""
        if post.get("job_id"):
            found = self.repo.get_job(post["job_id"])
            if found:
                return found
        raw_url = str(post.get("url") or "").strip()
        if raw_url:
            found = self.repo.get_job_by_url(raw_url)
            if found:
                return found
        return self.repo.get_job_by_url(f"recruiter://post/{post['id']}")

    @staticmethod
    def _has_real_ai_evaluation(post: dict) -> bool:
        return (
            post.get("ai_evaluated_at") is not None
            and post.get("ai_classification") == "vaga_ativa"
            and post.get("ai_score") is not None
        )

    def _record_post_evaluation(
        self,
        *,
        job_id: str,
        job_url: str,
        portal: str,
        score: int,
        verdict: str,
        summary: str,
        best_email: str = "",
        ai_model: Optional[str] = None,
        subscores: Optional[Dict[str, int]] = None,
        strengths: Optional[List[str]] = None,
        gaps: Optional[List[str]] = None,
        location_verdict: Optional[str] = None,
        language_gate: Optional[str] = None,
        language_note: Optional[str] = None,
        guard_alert: Optional[str] = None,
    ) -> None:
        """Persist evaluation metadata and quick evaluation markdown for promoted/saved recruiter posts."""
        prev_db: dict[str, Any] = {}
        try:
            prev_db = self.repo.get_latest_evaluation_details([job_id]).get(job_id) or {}
        except Exception as exc:
            logger.warning("Failed to load prior evaluation details for %s: %s", job_id, exc)

        prev_cached: dict[str, Any] = {}
        eval_file: Optional[Path] = None
        try:
            h = hashlib.sha256(job_url.encode("utf-8")).hexdigest()[:16]
            eval_file = painel_ia.PAINEL_DIR / f"{h}_avaliacao.md"
        except (TypeError, ValueError):
            eval_file = None

        if job_url and not (subscores and strengths and gaps) and eval_file is not None and eval_file.exists():
            try:
                content = eval_file.read_text(encoding="utf-8")
                details = painel_ia.extract_eval_details_from_md(content)
                if isinstance(details, dict):
                    prev_cached.update({k: v for k, v in details.items() if v})
                m_model = re.search(r"Modelo(?:\s+IA)?\s*[:=]\s*[*`]*\s*([^\n*`]+)", content, re.IGNORECASE)
                if m_model and not prev_cached.get("ai_model"):
                    prev_cached["ai_model"] = m_model.group(1).strip(" *`")
                m_sum = re.search(
                    r"##+\s*Resumo[^\n]*\n+(.+?)(?:\n\n|\n-\s*URL:|\nURL:|$)",
                    content,
                    re.IGNORECASE | re.DOTALL,
                )
                if m_sum and not prev_cached.get("summary"):
                    prev_cached["summary"] = m_sum.group(1).strip()
            except (OSError, ValueError, TypeError) as exc:
                logger.warning("Failed to inspect cached evaluation markdown for %s: %s", job_url, exc)

        resolved_subscores = (
            subscores
            if isinstance(subscores, dict) and subscores
            else (prev_db.get("subscores") or prev_cached.get("subscores") or {})
        )
        resolved_strengths = strengths if strengths else (prev_db.get("strengths") or prev_cached.get("strengths") or [])
        resolved_gaps = gaps if gaps else (prev_db.get("gaps") or prev_cached.get("gaps") or [])
        resolved_location_verdict = location_verdict or prev_db.get("location_verdict") or prev_cached.get("location_verdict")
        resolved_language_gate = language_gate or prev_db.get("language_gate") or prev_cached.get("language_gate")
        resolved_language_note = language_note or prev_db.get("language_note") or prev_cached.get("language_note")
        resolved_guard_alert = guard_alert or prev_cached.get("guard_alert")

        model_used = (
            (ai_model or "").strip()
            or (prev_db.get("ai_model") or "").strip()
            or (prev_cached.get("ai_model") or "").strip()
            or painel_ia.get_active_model_name()
        )
        clean_summary = (summary or "").strip() or (prev_cached.get("summary") or "").strip() or "Triagem concluída."
        email_note = f" | E-mail direto: {best_email}" if (best_email and best_email.lower() not in clean_summary.lower()) else ""
        full_summary = f"{clean_summary}{email_note}".strip()
        subs = resolved_subscores if isinstance(resolved_subscores, dict) else {}

        try:
            self.repo.insert_evaluation({
                "job_id": job_id,
                "score_technical": subs.get("technical"),
                "score_experience": subs.get("experience"),
                "score_behavioral": subs.get("behavioral"),
                "score_location": resolved_location_verdict,
                "score_career": subs.get("career"),
                "score_global": int(score),
                "verdict": verdict,
                "language_gate": resolved_language_gate,
                "language_note": resolved_language_note,
                "strengths": resolved_strengths,
                "gaps": resolved_gaps,
                "report_md": full_summary,
                "ai_provider": model_used,
            })
        except (RepositoryError, Exception) as exc:
            logger.warning("Failed to record recruiter evaluation for job %s: %s", job_id, exc)

        try:
            if eval_file is not None:
                eval_file.parent.mkdir(parents=True, exist_ok=True)
                if not eval_file.exists() or eval_file.read_text(encoding="utf-8").startswith("## Triagem rápida"):
                    rendered = painel_ia._render_quick_eval_md(
                        job_url,
                        portal,
                        model_used,
                        {
                            "score": int(score),
                            "verdict": verdict,
                            "summary": full_summary,
                            "subscores": subs,
                            "location_verdict": resolved_location_verdict or "PASS",
                            "language_gate": resolved_language_gate or "PASS",
                            "language_note": resolved_language_note or "",
                            "strengths": resolved_strengths,
                            "gaps": resolved_gaps,
                            "guard_alert": resolved_guard_alert or "",
                        },
                    )
                    eval_file.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write recruiter quick evaluation markdown for %s: %s", job_url, exc)

    def _transition_post_to_job_status(
        self,
        post: dict,
        *,
        existing: Optional[dict],
        decision: str,
        source: str,
        note_prefix: str,
        should_mark: bool = True,
    ) -> Tuple[str, str]:
        """Materialize a job row, persist AI triage details if present, transition status, and link post."""
        best_email = (post.get("ai_best_email") or ((post.get("emails") or [""])[0]) or "").strip()
        has_real_ai = self._has_real_ai_evaluation(post)
        score = int(post["ai_score"]) if has_real_ai else None
        verdict = post.get("ai_verdict") if has_real_ai else None

        jid, job_url, job_payload = self._prepare_job_from_post(
            post,
            score=score,
            verdict=verdict,
            best_email=best_email,
            existing=existing,
        )

        if has_real_ai and score is not None:
            ai_details = post.get("ai_details") if isinstance(post.get("ai_details"), dict) else {}
            self._record_post_evaluation(
                job_id=jid,
                job_url=job_payload["url"],
                portal=job_payload["portal"],
                score=score,
                verdict=str(verdict or ""),
                summary=str(post.get("ai_summary") or ""),
                best_email=best_email,
                ai_model=post.get("ai_model"),
                subscores=ai_details.get("subscores"),
                strengths=ai_details.get("strengths"),
                gaps=ai_details.get("gaps"),
                location_verdict=ai_details.get("location_verdict"),
                language_gate=ai_details.get("language_gate"),
                language_note=ai_details.get("language_note"),
                guard_alert=ai_details.get("guard_alert"),
            )

        if should_mark:
            note = f"{note_prefix} ({best_email})" if best_email else note_prefix
            self.repo.mark_jobs([jid], decision=decision, source=source, note=note)

        self.repo.link_recruiter_post_to_job(post["id"], jid)
        return jid, job_url

    def save_post_as_interested(self, post_id: int) -> dict:
        """Manually move a recruiter post to Me Interessam without auto-generating CV/Letter."""
        post = self.repo.get_recruiter_post(post_id)
        if not post:
            raise LookupError("Publicação não encontrada.")

        existing = self._find_existing_job_for_post(post)
        if existing and existing.get("status") in APPLIED_PIPELINE_STATUSES:
            raise ValueError("Esta oportunidade já foi registrada em Minhas Candidaturas.")

        should_mark = not existing or existing.get("status") != "interested"
        jid, job_url = self._transition_post_to_job_status(
            post,
            existing=existing,
            decision="interested",
            source="manual_recruiter",
            note_prefix="Salvo manualmente de Recrutadores",
            should_mark=should_mark,
        )
        return {"ok": True, "post_id": post_id, "job_id": jid, "url": job_url}

    def mark_post_contacted(
        self,
        post_id: int,
        email: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Record a direct email outreach into Minhas Candidaturas without generating CV/Letter."""
        post = self.repo.get_recruiter_post(post_id)
        if not post:
            raise LookupError("Publicação não encontrada.")

        target_email = (
            (email or "").strip()
            or (post.get("ai_best_email") or "").strip()
            or ((post.get("emails") or [""])[0] if post.get("emails") else "")
        ).strip().lower()
        if not target_email or "@" not in target_email:
            raise ValueError("Informe um e-mail de contato válido para registrar o envio.")

        previous_contact = self.repo.get_contacted_recruiter_emails().get(target_email)
        existing = self._find_existing_job_for_post(post)

        has_real_ai = self._has_real_ai_evaluation(post)
        score = int(post["ai_score"]) if has_real_ai else None
        verdict = post.get("ai_verdict") if has_real_ai else None
        jid, job_url, _ = self._prepare_job_from_post(
            post,
            score=score,
            verdict=verdict,
            best_email=target_email,
            existing=existing,
        )

        today_iso = date.today().isoformat()
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        app_notes = (notes or "").strip() or f"E-mail direto: {target_email}"
        company_name = post.get("company") or "Empresa"
        role_title = post.get("title") or "Cargo"
        portal_name = post.get("portal") or "recruiter_radar"

        from backend.core.tracker import TrackerService

        app_id, _ = TrackerService.persist_application_bundle(
            self.repo,
            job_id=jid,
            url=job_url,
            company=company_name,
            role=role_title,
            portal=portal_name,
            applied_date=today_iso,
            notes=app_notes,
            source="recruiter_outreach",
            contact_channel="recruiter_email",
            contacted_email=target_email,
            recruiter_post_id=post_id,
            contacted_at=now_iso,
            strict_legacy=False,
        )

        return {
            "ok": True,
            "post_id": post_id,
            "job_id": jid,
            "application_id": app_id,
            "url": job_url,
            "contacted_email": target_email,
            "contacted_at": now_iso,
            "previous_contact": previous_contact,
        }

    def promote_post_to_interested(
        self,
        post: dict,
        run_id: str,
        score: int,
        verdict: str,
        summary: str,
        best_email: str,
        ai_model: Optional[str] = None,
        *,
        subscores: Optional[Dict[str, int]] = None,
        strengths: Optional[List[str]] = None,
        gaps: Optional[List[str]] = None,
        location_verdict: Optional[str] = None,
        language_gate: Optional[str] = None,
        language_note: Optional[str] = None,
        guard_alert: Optional[str] = None,
    ) -> Optional[str]:
        """Create or link a job row from a qualified recruiter post and move it to Me Interessam."""
        post_id = post["id"]
        existing = self._find_existing_job_for_post(post)
        if existing and existing.get("status") in ("interested", *EXCLUDED_RADAR_JOB_STATUSES):
            return None

        model_used = (ai_model or post.get("ai_model") or "").strip() or painel_ia.get_active_model_name()
        email_note = f" | E-mail direto: {best_email}" if best_email else ""
        jid, _job_url, job_payload = self._prepare_job_from_post(
            post,
            score=int(score),
            verdict=verdict,
            best_email=best_email,
            existing=existing,
        )

        note = f"[auto:{run_id}] Recrutador {int(score)}/100 - {verdict}{email_note}"
        self.repo.mark_jobs(
            [jid],
            decision="interested",
            source="auto_triage_recruiter",
            note=note,
        )

        self._record_post_evaluation(
            job_id=jid,
            job_url=job_payload["url"],
            portal=job_payload["portal"],
            score=int(score),
            verdict=verdict,
            summary=summary,
            best_email=best_email,
            ai_model=model_used,
            subscores=subscores,
            strengths=strengths,
            gaps=gaps,
            location_verdict=location_verdict,
            language_gate=language_gate,
            language_note=language_note,
            guard_alert=guard_alert,
        )

        self.repo.mark_recruiter_post_promoted(post_id, jid, run_id=run_id)
        return jid

    def triage_posts(
        self,
        *,
        post_ids: Optional[List[int]] = None,
        query: Optional[str] = None,
        portal: Optional[str] = None,
        limit: int = 12,
    ) -> dict:
        """Run on-demand AI triage over untriaged recruiter posts and persist scores/classifications."""
        providers_mod = _facade_ai_providers()
        env = providers_mod.load_env_file()
        if not providers_mod.has_consent(env):
            raise ValueError(
                "Consentimento de IA necessário: acesse Configurações e confirme o envio do perfil antes de triar."
            )
        if not painel_ia.is_available():
            raise ValueError(
                "Nenhum provedor de IA ativo/configurado. Verifique suas credenciais em Configurações."
            )

        capped_limit = max(1, min(25, int(limit or 12)))
        requested_ids = {int(pid) for pid in (post_ids or []) if pid is not None}
        candidates = self.repo.list_recruiter_posts(
            query=query,
            portal=portal,
            include_non_jobs=True,
            only_untriaged=True,
            include_without_email=bool(requested_ids),
        )
        if requested_ids:
            candidates = [p for p in candidates if int(p.get("id") or -1) in requested_ids]

        candidates.sort(
            key=lambda p: (
                PORTAL_PRIORITY.get(str(p.get("portal") or ""), 2),
                int(p.get("match_score") or 0),
                str(p.get("published_date") or ""),
            ),
            reverse=True,
        )
        batch = candidates[:capped_limit]
        if not batch:
            return {
                "ok": True,
                "triaged": 0,
                "active_jobs": 0,
                "talent_pools_discarded": 0,
                "not_a_job": 0,
                "errors": 0,
                "posts": [],
            }

        results: List[Tuple[int, dict]] = []
        errors = 0

        def _evaluate_one(post: dict) -> Tuple[int, Optional[dict]]:
            return post["id"], painel_ia.triar_post_recrutador(post)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_evaluate_one, post) for post in batch]
            for fut in futures:
                try:
                    pid, res = fut.result()
                    if isinstance(res, dict):
                        results.append((pid, res))
                    else:
                        errors += 1
                except Exception as exc:
                    logger.warning("Manual recruiter AI triage failed for a post: %s", exc)
                    errors += 1

        active_jobs = 0
        talent_pools_discarded = 0
        not_a_job = 0
        updated_posts: List[dict] = []

        for pid, res in results:
            cls = res["classification"]
            score = int(res["score"])
            verdict = res["verdict"]
            summary = res["summary"]
            best_email = res["best_email"]
            ai_model = res.get("ai_model")
            ai_details = {
                k: res.get(k)
                for k in (
                    "subscores",
                    "strengths",
                    "gaps",
                    "location_verdict",
                    "language_gate",
                    "language_note",
                    "guard_alert",
                )
                if res.get(k)
            } or None

            self.repo.update_recruiter_post_ai(
                pid,
                cls,
                score,
                verdict,
                summary,
                best_email,
                auto_dismissed=False,
                ai_model=ai_model,
                ai_details=ai_details,
            )
            if cls == "banco_talentos":
                talent_pools_discarded += 1
            elif cls == "nao_e_vaga":
                not_a_job += 1
            else:
                active_jobs += 1

            refreshed = self.repo.get_recruiter_post(pid)
            if refreshed:
                updated_posts.append(refreshed)

        return {
            "ok": True,
            "triaged": len(results),
            "active_jobs": active_jobs,
            "talent_pools_discarded": talent_pools_discarded,
            "not_a_job": not_a_job,
            "errors": errors,
            "posts": updated_posts,
        }

    def _move_post_to_discarded(self, post_id: int) -> bool:
        """Move a recruiter post into Descartadas (jobs.status='discarded') while preserving dedup protection."""
        post = self.repo.get_recruiter_post(post_id)
        if not post or post.get("dismissed"):
            return False

        existing = self._find_existing_job_for_post(post)
        if existing and existing.get("status") in ("discarded", "skipped"):
            if post.get("job_id") != existing["id"]:
                self.repo.link_recruiter_post_to_job(post_id, existing["id"])
                return True
            return False

        if existing and existing.get("status") == "applied":
            return self.repo.dismiss_recruiter_post(post_id)

        self._transition_post_to_job_status(
            post,
            existing=existing,
            decision="discarded",
            source="recruiter_discard",
            note_prefix="Descartado em Recrutadores",
            should_mark=True,
        )
        return True
