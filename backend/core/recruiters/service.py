"""Orchestrator service for the recruiter posts radar (listing, paste/batch, sync, triage)."""

from __future__ import annotations

import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from backend.core.constants import EXCLUDED_RADAR_JOB_STATUSES
from backend.core.recruiters.collectors import RecruiterCollectorsMixin
from backend.core.recruiters.parser import (
    extract_clean_emails,
    extract_email_context,
    extract_linkedin_activity_id,
    extract_linkedin_snowflake_date,
    get_all_cv_keywords,
    infer_work_model_and_location,
    is_hn_candidate_seeking_post,
    match_cv_keywords,
    parse_linkedin_batch_text,
    parse_relative_age_date,
)
from backend.core.recruiters.search_terms import expand_search_term_with_ai
from backend.core.recruiters.triage import RecruiterTriageMixin
from backend.db.repository import Repository


def _resolve_matcher() -> Any:
    mod = sys.modules.get("backend.core.recruiter_service")
    return getattr(mod, "match_cv_keywords", match_cv_keywords) if mod is not None else match_cv_keywords


class RecruiterService(RecruiterCollectorsMixin, RecruiterTriageMixin):
    """Encapsulates business operations for recruiter posts radar."""

    def __init__(
        self,
        repo: Repository,
        enable_live_feeds: bool = True,
        cache_dir: Optional[Path] = None,
    ):
        self.repo = repo
        self.enable_live_feeds = enable_live_feeds
        self._cache_dir: Optional[Path] = Path(cache_dir) if cache_dir else None
        self._feed_cache: Dict[str, Any] = {}
        self._github_etags: Dict[str, Any] = {}
        self._github_rate_limit_until: float = 0.0
        self._feed_lock = threading.Lock()
        self._repo_lock = threading.RLock()
        self._health_lock = threading.RLock()
        if self._cache_dir is not None:
            self._load_github_disk_cache()

    @staticmethod
    def default_cache_dir() -> Path:
        """Resolve the runtime cache directory without leaking tools imports into API dependencies."""
        from backend.tools import painel_ia

        return painel_ia.PAINEL_DIR

    @staticmethod
    def _is_row_visible_in_radar(
        *,
        portal: Optional[str],
        dismissed: Any,
        auto_promoted: Any,
        job_status: Optional[str],
    ) -> bool:
        """Mirror repository.list_recruiter_posts visibility rules for active radar posts."""
        if dismissed:
            return False
        if job_status in EXCLUDED_RADAR_JOB_STATUSES:
            return False
        return True

    def _is_post_visible_in_radar(self, post_id: int) -> bool:
        """Check whether an upserted recruiter post is active and visible in the Recrutadores listing."""
        row = self.repo.get_recruiter_post_visibility(post_id)
        if not row:
            return False
        return self._is_row_visible_in_radar(
            portal=row.get("portal"),
            dismissed=row.get("dismissed"),
            auto_promoted=row.get("auto_promoted"),
            job_status=row.get("job_status"),
        )

    def _build_pasted_post_data(
        self,
        raw_text: str,
        *,
        url: Optional[str] = None,
        title: Optional[str] = None,
        company: Optional[str] = None,
        location: Optional[str] = None,
        work_model: Optional[str] = None,
        published_date: Optional[str] = None,
        posted_age_text: Optional[str] = None,
        cv_keywords: Optional[List[str]] = None,
        allow_without_email: bool = False,
    ) -> dict:
        """Normalize and validate a pasted/captured recruiter post into repository payload."""
        text = (raw_text or "").strip()
        if not text:
            raise ValueError("O texto da publicação não pode estar vazio.")

        emails = extract_clean_emails(text)
        clean_url = (url or "").strip() or None
        if not emails:
            if not allow_without_email:
                raise ValueError("Nenhum endereço de e-mail válido foi encontrado no texto.")
            if not clean_url and len(text) < 25:
                raise ValueError("Publicação do LinkedIn sem link ou texto suficiente.")

        clean_title = (title or "").strip()
        if not clean_title:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            clean_title = (lines[0] if lines else "Publicação de Recrutador")[:90]

        clean_company = (company or "").strip() or "Recrutador / Empresa"

        if published_date and re.match(r"^\d{4}-\d{2}-\d{2}", str(published_date).strip()):
            resolved_date: Optional[str] = str(published_date).strip()[:10]
        else:
            resolved_date = (
                extract_linkedin_snowflake_date(clean_url)
                or extract_linkedin_snowflake_date(text)
                or parse_relative_age_date(posted_age_text)
            )

        inferred_wm, inferred_loc = infer_work_model_and_location(
            clean_title,
            text,
            labels=[location or ""],
            default_location="Remoto / A Definir",
        )
        clean_location = (location or "").strip() or inferred_loc or "Remoto / A Definir"
        clean_wm = (work_model or "").strip() or inferred_wm

        primary_email = emails[0] if emails else ""
        context = extract_email_context(text, primary_email) if primary_email else ""

        kws_pool = cv_keywords if cv_keywords is not None else get_all_cv_keywords()
        matcher = _resolve_matcher()
        matched_kws, score = matcher(f"{clean_title} {text}", kws_pool)

        return {
            "emails": emails,
            "email_context": context,
            "title": clean_title[:120],
            "company": clean_company[:80],
            "portal": "linkedin_post",
            "url": clean_url,
            "location": clean_location,
            "work_model": clean_wm,
            "published_date": resolved_date,
            "description": text,
            "matched_keywords": matched_kws,
            "match_score": score,
            "job_id": None,
        }

    def add_pasted_post(
        self,
        raw_text: str,
        url: Optional[str] = None,
        title: Optional[str] = None,
        company: Optional[str] = None,
        location: Optional[str] = None,
        work_model: Optional[str] = None,
        published_date: Optional[str] = None,
        allow_without_email: bool = False,
    ) -> dict:
        """Parse and save a manually pasted post from LinkedIn or other feed."""
        post_data = self._build_pasted_post_data(
            raw_text,
            url=url,
            title=title,
            company=company,
            location=location,
            work_model=work_model,
            published_date=published_date,
            allow_without_email=allow_without_email,
        )
        with self._repo_lock:
            post_id = self.repo.upsert_recruiter_post(post_data)
            saved = self.repo.get_recruiter_post(post_id)
        if saved:
            return saved
        post_data["id"] = post_id
        return post_data

    def add_pasted_posts_batch(
        self,
        items: Optional[List[Dict[str, Any]]] = None,
        *,
        raw_batch_text: Optional[str] = None,
        allow_without_email: bool = False,
    ) -> dict:
        """Import a batch of LinkedIn/clipboard posts safely with Snowflake dates and deduplication."""
        entries: List[Dict[str, Any]] = []
        if items:
            entries.extend(dict(it) for it in items if isinstance(it, dict))
        if raw_batch_text and raw_batch_text.strip():
            entries.extend(parse_linkedin_batch_text(raw_batch_text))

        if not entries:
            raise ValueError("Nenhuma publicação válida encontrada para importar.")

        cv_keywords = get_all_cv_keywords()
        imported = 0
        updated = 0
        skipped = 0
        invalid = 0
        saved_posts: List[dict] = []
        matched_post_ids: List[int] = []
        seen_matched_ids: Set[int] = set()

        def _record_matched_id(raw_id: Any) -> None:
            if raw_id is None:
                return
            pid_int = int(raw_id)
            if pid_int not in seen_matched_ids:
                seen_matched_ids.add(pid_int)
                matched_post_ids.append(pid_int)

        for entry in entries:
            try:
                post_data = self._build_pasted_post_data(
                    str(entry.get("raw_text") or entry.get("text") or ""),
                    url=entry.get("url"),
                    title=entry.get("title"),
                    company=entry.get("company") or entry.get("author"),
                    location=entry.get("location"),
                    work_model=entry.get("work_model"),
                    published_date=entry.get("published_date"),
                    posted_age_text=entry.get("posted_age_text"),
                    cv_keywords=cv_keywords,
                    allow_without_email=allow_without_email,
                )
            except ValueError:
                invalid += 1
                continue

            act_id = extract_linkedin_activity_id(post_data.get("url") or post_data.get("description"))
            with self._repo_lock:
                existing = self.repo.find_recruiter_post_for_dedup(
                    url=post_data.get("url"),
                    linkedin_activity_id=act_id,
                    primary_email=post_data["emails"][0] if post_data.get("emails") else None,
                    description=post_data["description"],
                    title=post_data.get("title"),
                )
                if existing:
                    if self._is_row_visible_in_radar(
                        portal=existing.get("portal"),
                        dismissed=existing.get("dismissed"),
                        auto_promoted=existing.get("auto_promoted"),
                        job_status=existing.get("job_status"),
                    ):
                        _record_matched_id(existing.get("id"))

                    is_closed = bool(existing.get("dismissed")) or bool(existing.get("auto_promoted")) or (
                        existing.get("job_status") in ("applied", "interested", "discarded", "skipped")
                    )
                    if is_closed or existing.get("ai_evaluated_at"):
                        skipped += 1
                        continue

                    prev_desc = str(existing.get("description") or "")
                    can_enrich = (
                        len(post_data["description"]) > len(prev_desc) + 20
                        or (post_data.get("published_date") and not existing.get("published_date"))
                    )
                    if can_enrich and existing.get("url"):
                        post_data["url"] = existing["url"]
                        post_id = self.repo.upsert_recruiter_post(post_data)
                        post_data["id"] = post_id
                        saved_posts.append(post_data)
                        _record_matched_id(post_id)
                        updated += 1
                    else:
                        skipped += 1
                    continue

                post_id = self.repo.upsert_recruiter_post(post_data)
                post_data["id"] = post_id
                saved_posts.append(post_data)
                _record_matched_id(post_id)
                imported += 1

        if imported == 0 and updated == 0 and skipped == 0 and invalid > 0:
            raise ValueError("Nenhum endereço de e-mail válido foi encontrado nas publicações enviadas.")

        return {
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "invalid": invalid,
            "posts": saved_posts,
            "matched_post_ids": matched_post_ids,
        }

    def list_posts(
        self,
        query: Optional[str] = None,
        only_cv: bool = False,
        portal: Optional[str] = None,
        include_non_jobs: bool = True,
    ) -> List[dict]:
        """List active recruiter posts enriched with prior email outreach warnings and normalized metadata."""
        posts = self.repo.list_recruiter_posts(
            query=query,
            only_cv=only_cv,
            portal=portal,
            include_non_jobs=include_non_jobs,
        )
        contacted_map = self.repo.get_contacted_recruiter_emails()
        cv_keywords = get_all_cv_keywords()
        matcher = _resolve_matcher()
        filtered_out: List[dict] = []
        for post in posts:
            p_portal = str(post.get("portal") or "")
            p_title = str(post.get("title") or "")
            p_desc = str(post.get("description") or "")
            if p_portal == "hn-search" and is_hn_candidate_seeking_post(p_desc):
                continue
            if p_portal == "github-vagas" and re.match(r"^(?:question\s+about|d[úu]vida\s+sobre|how\s+to)\b", p_title, re.IGNORECASE):
                continue

            if not post.get("work_model"):
                inferred_wm, _ = infer_work_model_and_location(
                    p_title,
                    p_desc,
                    labels=[str(post.get("location") or "")],
                )
                if not inferred_wm and p_portal in ("remotar-search", "remotive-search", "remoteok-search", "jobicy-search"):
                    inferred_wm = "remoto"
                if inferred_wm:
                    post["work_model"] = inferred_wm

            if not post.get("matched_keywords") and cv_keywords:
                kws, sc = matcher(f"{p_title} {p_desc}", cv_keywords)
                if kws:
                    post["matched_keywords"] = kws
                    post["match_score"] = sc

            matches: List[dict] = []
            seen_em: Set[str] = set()
            for em in post.get("emails") or []:
                norm = str(em).strip().lower()
                if not norm or norm in seen_em:
                    continue
                seen_em.add(norm)
                info = contacted_map.get(norm)
                if info:
                    matches.append(info)
            post["previously_contacted"] = matches
            filtered_out.append(post)
        return filtered_out

    def dismiss_post(self, post_id: int) -> bool:
        """Move a recruiter post to Descartadas."""
        with self._repo_lock:
            return self._move_post_to_discarded(post_id)

    def dismiss_posts(self, post_ids: list[int]) -> list[int]:
        """Move multiple recruiter posts to Descartadas in one idempotent batch."""
        clean_ids: list[int] = []
        seen: set[int] = set()
        for raw_id in post_ids or []:
            try:
                pid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if pid > 0 and pid not in seen:
                seen.add(pid)
                clean_ids.append(pid)

        moved_ids: list[int] = []
        with self._repo_lock:
            for pid in clean_ids:
                if self._move_post_to_discarded(pid):
                    moved_ids.append(pid)
        return moved_ids

    def expand_search_term(self, term: str) -> Dict[str, Any]:
        """Expand a search keyword into its PT/EN LinkedIn market equivalent using configured AI + cache."""
        return expand_search_term_with_ai(term)
