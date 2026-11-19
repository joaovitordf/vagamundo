"""Multi-source recruiter feed collectors (local DB, caches, GitHub Vagas, HN, Remotive, live portals)."""

from __future__ import annotations

import glob
import inspect
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.core.constants import EXCLUDED_RADAR_JOB_STATUSES, atomic_write_json
from backend.core.recruiters.parser import (
    DEFAULT_FEED_CACHE_TTL,
    LIVE_PORTAL_SPECS,
    RECRUITER_GITHUB_REPOS,
    RECRUITER_LIVE_PORTALS,
    ROLE_PREFIX_RE,
    extract_clean_emails,
    extract_email_context,
    get_all_cv_keywords,
    html_to_text,
    infer_work_model_and_location,
    is_hn_candidate_seeking_post,
    match_cv_keywords,
    parse_hn_header_meta,
    strip_accents,
    tokenize_search_keywords,
)
from backend.tools import scrape_run

logger = logging.getLogger(__name__)
_HEALTH_SYNC_LOCK = threading.RLock()


def _facade_attr(name: str, default: Any) -> Any:
    """Resolve attribute via backend.core.recruiter_service when present so test patches work seamlessly."""
    mod = sys.modules.get("backend.core.recruiter_service")
    return getattr(mod, name, default) if mod is not None else default


class RecruiterCollectorsMixin:
    """Collects and deduplicates recruiter publications across local and external feeds."""

    def _get_cached_feed(self, key: str, ttl_seconds: int) -> Any:
        if ttl_seconds <= 0:
            return None
        with self._feed_lock:
            entry = self._feed_cache.get(key)
        if not entry:
            return None
        stored_at, payload = entry
        if (time.monotonic() - stored_at) <= ttl_seconds:
            return payload
        return None

    def _set_cached_feed(self, key: str, payload: Any) -> None:
        with self._feed_lock:
            self._feed_cache[key] = (time.monotonic(), payload)

    def _github_disk_cache_path(self) -> Optional[Path]:
        if not self._cache_dir:
            return None
        return self._cache_dir / "github_vagas_cache.json"

    @staticmethod
    def _parse_github_reset_ts(headers: Any, now: Optional[float] = None) -> float:
        base = now if now is not None else time.time()
        raw_reset = headers.get("X-RateLimit-Reset") if headers else None
        try:
            reset_ts = float(raw_reset)
            if reset_ts > base:
                return min(reset_ts + 5.0, base + 3600.0)
        except (TypeError, ValueError):
            pass
        return base + 900.0

    def _load_github_disk_cache(self) -> None:
        cache_path = self._github_disk_cache_path()
        if not cache_path or not cache_path.is_file():
            return
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return

        now_wall = time.time()
        now_mono = time.monotonic()
        with self._feed_lock:
            rl_until = data.get("rate_limit_until")
            if isinstance(rl_until, (int, float)) and rl_until > now_wall:
                self._github_rate_limit_until = min(float(rl_until), now_wall + 3600.0)
            repos = data.get("repos")
            if isinstance(repos, dict):
                for repo, entry in repos.items():
                    if not isinstance(entry, dict):
                        continue
                    items = entry.get("items")
                    if not isinstance(items, list):
                        continue
                    etag = str(entry.get("etag") or "")
                    self._github_etags[repo] = (etag, items)
                    stored_at = entry.get("stored_at")
                    if isinstance(stored_at, (int, float)):
                        age = max(0.0, now_wall - float(stored_at))
                        if age <= DEFAULT_FEED_CACHE_TTL:
                            self._feed_cache[f"github:{repo}"] = (now_mono - age, items)

    def _save_github_disk_cache(self) -> None:
        cache_path = self._github_disk_cache_path()
        if not cache_path:
            return
        now_wall = time.time()
        now_mono = time.monotonic()
        with self._feed_lock:
            repos_payload: Dict[str, Any] = {}
            for repo, (etag, items) in self._github_etags.items():
                if not isinstance(items, list):
                    continue
                feed_entry = self._feed_cache.get(f"github:{repo}")
                stored_wall = (
                    now_wall - max(0.0, now_mono - feed_entry[0])
                    if feed_entry
                    else (now_wall - DEFAULT_FEED_CACHE_TTL)
                )
                repos_payload[repo] = {
                    "etag": etag,
                    "stored_at": round(stored_wall, 3),
                    "items": items,
                }
            payload = {
                "rate_limit_until": self._github_rate_limit_until,
                "repos": repos_payload,
            }
        try:
            atomic_write_json(cache_path, payload, indent=0)
        except OSError as exc:
            logger.debug("Não foi possível persistir cache GitHub Vagas em disco: %s", exc)

    @staticmethod
    def _record_fetch_error(
        exc: Exception,
        status_out: Optional[dict],
        portal: Optional[str] = None,
        label: Optional[str] = None,
    ) -> bool:
        code = getattr(exc, "code", None)
        msg = str(exc).lower()
        is_rate_limit = bool(code in (403, 429, 503) or "429" in msg or "rate" in msg or "too many" in msg)
        if status_out is None:
            return is_rate_limit
        with _HEALTH_SYNC_LOCK:
            status_out["errors"] = int(status_out.get("errors", 0)) + 1
            if is_rate_limit:
                status_out["rate_limited"] = True
            if portal:
                by_portal = status_out.setdefault("by_portal", {})
                entry = by_portal.setdefault(portal, {"fetched": 0, "matched": 0, "errors": 0, "last_error": None})
                entry["errors"] = int(entry.get("errors", 0)) + 1
                err_desc = "rate limit (HTTP 403/429)" if is_rate_limit else str(exc)[:140]
                entry["last_error"] = err_desc
                warnings = status_out.setdefault("warnings", [])
                human_name = label or portal
                warn_msg = (
                    f"{human_name} atingiu limite temporário de requisições"
                    if is_rate_limit
                    else f"Falha parcial ao consultar {human_name}"
                )
                if warn_msg not in warnings:
                    warnings.append(warn_msg)
        return is_rate_limit

    @staticmethod
    def _record_source_hit(status_out: Optional[dict], portal: str, *, matched: bool) -> None:
        if status_out is None or not portal:
            return
        with _HEALTH_SYNC_LOCK:
            by_portal = status_out.setdefault("by_portal", {})
            entry = by_portal.setdefault(portal, {"fetched": 0, "matched": 0, "errors": 0, "last_error": None})
            entry["fetched"] = int(entry.get("fetched", 0)) + 1
            if matched:
                entry["matched"] = int(entry.get("matched", 0)) + 1

    def _upsert_collected_post(
        self,
        *,
        title: str,
        company: str,
        portal: str,
        url: Optional[str],
        location: Optional[str],
        work_model: Optional[str],
        published_date: Optional[str],
        description: str,
        cv_keywords: List[str],
        extra_text: str = "",
        job_id: Optional[int] = None,
        match_tokens: Optional[List[str]] = None,
        collected_urls: Optional[Set[str]] = None,
        matched_post_ids: Optional[Set[int]] = None,
        status_out: Optional[dict] = None,
    ) -> bool:
        """Extract clean emails from description, compute CV match score and upsert if valid."""
        emails = extract_clean_emails(description)
        if not emails:
            return False

        primary_email = emails[0]
        context = extract_email_context(description, primary_email)
        matcher = _facade_attr("match_cv_keywords", match_cv_keywords)
        matched_kws, score = matcher(f"{title} {extra_text} {description}", cv_keywords)

        effective_wm = work_model
        if not effective_wm:
            effective_wm, _ = infer_work_model_and_location(
                title or "",
                description or "",
                labels=[location or "", extra_text or ""],
                default_location=location or "Brasil",
            )
            if not effective_wm and portal in ("remotar-search", "remotive-search", "remoteok-search", "jobicy-search"):
                effective_wm = "remoto"

        with self._repo_lock:
            post_id = self.repo.upsert_recruiter_post({
                "emails": emails,
                "email_context": context,
                "title": (title or "Oportunidade")[:120],
                "company": (company or "Recrutador / Empresa")[:80],
                "portal": portal,
                "url": url,
                "location": location or "Brasil",
                "work_model": effective_wm,
                "published_date": published_date,
                "description": description,
                "matched_keywords": matched_kws,
                "match_score": score,
                "job_id": job_id,
            })
            is_visible = self._is_post_visible_in_radar(post_id) if (matched_post_ids is not None and post_id) else False
        is_match = True
        if match_tokens:
            hay = strip_accents(f"{title} {company} {extra_text} {description}")
            is_match = any(tok in hay for tok in match_tokens)
        if is_match:
            with self._health_lock:
                if collected_urls is not None and url:
                    collected_urls.add(url)
                if matched_post_ids is not None and post_id and is_visible:
                    matched_post_ids.add(int(post_id))
        self._record_source_hit(status_out, portal, matched=is_match)
        return True

    def sync_from_jobs(
        self,
        query: Optional[str] = None,
        *,
        _matched_post_ids: Optional[Set[int]] = None,
        _status_out: Optional[dict] = None,
    ) -> dict:
        """Scan jobs in repository and sync any postings containing emails."""
        with self._repo_lock:
            candidates = self.repo.get_jobs_with_potential_emails()
        cv_keywords = get_all_cv_keywords()
        tokens = tokenize_search_keywords([q.strip() for q in (query or "").split(",") if q.strip()])
        matcher = _facade_attr("match_cv_keywords", match_cv_keywords)

        found_count = 0
        new_count = 0

        for j in candidates:
            desc = j.get("description") or ""
            emails = extract_clean_emails(desc)
            if not emails:
                continue

            found_count += 1
            primary_email = emails[0]
            context = extract_email_context(desc, primary_email)
            matched_kws, score = matcher(f"{j.get('title', '')} {desc}", cv_keywords)

            raw_wm = j.get("work_model") or j.get("workplace_type")
            if not raw_wm:
                raw_wm, _ = infer_work_model_and_location(
                    str(j.get("title") or ""),
                    desc,
                    labels=[str(j.get("location") or "")],
                )
                if not raw_wm and str(j.get("portal") or "") in ("remotar-search", "remotive-search", "remoteok-search", "jobicy-search"):
                    raw_wm = "remoto"

            post_data = {
                "emails": emails,
                "email_context": context,
                "title": j.get("title") or "Oportunidade",
                "company": j.get("company") or "Empresa",
                "portal": j.get("portal") or "jobs",
                "url": j.get("url"),
                "location": j.get("location"),
                "work_model": raw_wm,
                "published_date": j.get("posted_date"),
                "description": desc,
                "matched_keywords": matched_kws,
                "match_score": score,
                "job_id": j.get("id"),
            }

            with self._repo_lock:
                post_id = self.repo.upsert_recruiter_post(post_data)
                is_visible = self._is_post_visible_in_radar(post_id) if (_matched_post_ids is not None and post_id) else False
            new_count += 1
            is_match = True
            if tokens:
                hay = strip_accents(f"{j.get('title', '')} {j.get('company', '')} {desc}")
                is_match = any(tok in hay for tok in tokens)
            if _matched_post_ids is not None and post_id and is_visible and is_match:
                with self._health_lock:
                    _matched_post_ids.add(int(post_id))
            self._record_source_hit(_status_out, str(post_data["portal"]), matched=is_match)

        return {
            "scanned": len(candidates),
            "posts_with_email": found_count,
            "synced": new_count,
        }

    def sync_from_hn(
        self,
        query: str,
        limit: int = 50,
        cache_ttl_seconds: int = DEFAULT_FEED_CACHE_TTL,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
        _matched_post_ids: Optional[Set[int]] = None,
    ) -> int:
        """Search Hacker News Who is Hiring threads for clean hiring posts with direct emails."""
        if not query or not query.strip():
            return 0

        term = query.strip()
        try:
            story_ids = self._get_cached_feed("hn:story_ids", cache_ttl_seconds)
            if story_ids is None:
                url_story = (
                    "https://hn.algolia.com/api/v1/search_by_date"
                    "?tags=story,author_whoishiring&query=%22Who+is+hiring%22&hitsPerPage=6"
                )
                req = urllib.request.Request(url_story, headers={"User-Agent": "vagamundo/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    story_data = json.loads(resp.read().decode("utf-8"))

                story_ids = []
                for h in story_data.get("hits") or []:
                    st_title = str(h.get("title") or "").lower()
                    sid = str(h.get("objectID") or "").strip()
                    if sid and "who is hiring" in st_title:
                        story_ids.append(sid)
                if not story_ids:
                    raw_sid = str(((story_data.get("hits") or [{}])[0]).get("objectID") or "").strip()
                    if raw_sid:
                        story_ids.append(raw_sid)
                if story_ids:
                    self._set_cached_feed("hn:story_ids", story_ids)
            if not story_ids:
                return 0

            encoded_query = urllib.parse.quote(term)
            cv_keywords = get_all_cv_keywords()
            synced = 0

            for sid in story_ids[:2]:
                comments_key = f"hn:comments:{sid}:{term.lower()}"
                comments_hits = self._get_cached_feed(comments_key, cache_ttl_seconds)
                if comments_hits is None:
                    url_comments = (
                        f"https://hn.algolia.com/api/v1/search?tags=comment,story_{sid}"
                        f"&query={encoded_query}&hitsPerPage={limit}"
                    )
                    req_c = urllib.request.Request(url_comments, headers={"User-Agent": "vagamundo/1.0"})
                    with urllib.request.urlopen(req_c, timeout=6) as resp_c:
                        comments_data = json.loads(resp_c.read().decode("utf-8"))
                    comments_hits = comments_data.get("hits") or []
                    self._set_cached_feed(comments_key, comments_hits)

                for c in comments_hits:
                    parent_id = c.get("parent_id")
                    if parent_id is not None and str(parent_id) != str(sid):
                        continue

                    text = html_to_text(c.get("comment_text") or "")
                    if not text or is_hn_candidate_seeking_post(text):
                        continue

                    obj_id = c.get("objectID")
                    hn_url = f"https://news.ycombinator.com/item?id={obj_id}"
                    author = c.get("author") or "Recrutador HN"
                    created_at = (c.get("created_at") or "")[:10]
                    lines = [l.strip() for l in text.splitlines() if l.strip()]
                    header_line = lines[0] if lines else "Oportunidade Hacker News"
                    hn_work_model, hn_location = parse_hn_header_meta(header_line, text)

                    if self._upsert_collected_post(
                        title=header_line[:70],
                        company=f"{author} (Hacker News)",
                        portal="hn-search",
                        url=hn_url,
                        location=hn_location,
                        work_model=hn_work_model,
                        published_date=created_at,
                        description=text,
                        cv_keywords=cv_keywords,
                        collected_urls=_collected_urls,
                        matched_post_ids=_matched_post_ids,
                        status_out=_status_out,
                    ):
                        synced += 1

                if synced >= 3:
                    break

            return synced
        except urllib.error.HTTPError as ex:
            logger.warning("Erro HTTP ao sincronizar comentários do Hacker News (%s): %s", ex.code, ex)
            self._record_fetch_error(ex, _status_out, portal="hn-search", label="Hacker News")
            return 0
        except Exception as ex:
            logger.warning("Falha ao sincronizar comentários do Hacker News: %s", ex)
            self._record_fetch_error(ex, _status_out, portal="hn-search", label="Hacker News")
            return 0

    def sync_from_github_repos(
        self,
        query: Optional[str] = None,
        max_age_days: int = 90,
        cache_ttl_seconds: int = DEFAULT_FEED_CACHE_TTL,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
        _matched_post_ids: Optional[Set[int]] = None,
    ) -> int:
        """Mine active open issues with direct emails from Brazilian tech GitHub job boards."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
        cv_keywords = get_all_cv_keywords()
        tokens = tokenize_search_keywords([q.strip() for q in (query or "").split(",") if q.strip()])
        gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        base_headers = {"User-Agent": "vagamundo/1.0", "Accept": "application/vnd.github+json"}
        if gh_token:
            base_headers["Authorization"] = f"Bearer {gh_token}"

        synced = 0
        now_wall = time.time()
        with self._feed_lock:
            rl_until = self._github_rate_limit_until
        rate_limited_active = cache_ttl_seconds > 0 and now_wall < rl_until
        pause_logged = False

        def _mark_github_rate_limit(headers: Any) -> None:
            nonlocal rate_limited_active
            until = self._parse_github_reset_ts(headers, time.time())
            with self._feed_lock:
                if until > self._github_rate_limit_until:
                    self._github_rate_limit_until = until
            rate_limited_active = True
            self._save_github_disk_cache()

        def _warn_pause_once(status_out: Optional[dict]) -> None:
            nonlocal pause_logged
            if status_out is None or pause_logged:
                return
            pause_logged = True
            with self._feed_lock:
                rl_val = self._github_rate_limit_until
            reset_hhmm = datetime.fromtimestamp(rl_val).strftime("%H:%M")
            with self._health_lock, _HEALTH_SYNC_LOCK:
                by_portal = status_out.setdefault("by_portal", {})
                entry = by_portal.setdefault("github-vagas", {"fetched": 0, "matched": 0, "errors": 0, "last_error": None})
                entry["last_error"] = f"rate limit até {reset_hhmm}"
                warnings = status_out.setdefault("warnings", [])
                msg = f"GitHub Vagas BR em pausa temporária até {reset_hhmm} (limite da API sem GITHUB_TOKEN)"
                if msg not in warnings:
                    warnings.append(msg)

        github_repos = _facade_attr("RECRUITER_GITHUB_REPOS", RECRUITER_GITHUB_REPOS)
        for repo in github_repos:
            cache_key = f"github:{repo}"
            items = self._get_cached_feed(cache_key, cache_ttl_seconds)
            if items is None:
                with self._feed_lock:
                    etag_entry = self._github_etags.get(repo)

                if rate_limited_active:
                    _warn_pause_once(_status_out)
                    if etag_entry and isinstance(etag_entry[1], list):
                        items = etag_entry[1]
                    else:
                        continue
                else:
                    req_headers = dict(base_headers)
                    if etag_entry and etag_entry[0]:
                        req_headers["If-None-Match"] = etag_entry[0]
                    try:
                        api_url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=50"
                        req = urllib.request.Request(api_url, headers=req_headers)
                        with urllib.request.urlopen(req, timeout=7) as resp:
                            items = json.loads(resp.read().decode("utf-8"))
                            resp_headers = getattr(resp, "headers", None)
                            etag_val = resp_headers.get("ETag") if resp_headers else None
                            remaining_raw = resp_headers.get("X-RateLimit-Remaining") if resp_headers else None
                        if isinstance(items, list):
                            self._set_cached_feed(cache_key, items)
                            with self._feed_lock:
                                self._github_etags[repo] = (str(etag_val or ""), items)
                            if str(remaining_raw).strip() == "0":
                                _mark_github_rate_limit(resp_headers)
                                pause_logged = True
                            else:
                                self._save_github_disk_cache()
                    except urllib.error.HTTPError as ex:
                        if ex.code == 304 and etag_entry is not None:
                            items = etag_entry[1]
                            self._set_cached_feed(cache_key, items)
                            self._save_github_disk_cache()
                        else:
                            is_rl = self._record_fetch_error(ex, _status_out, portal="github-vagas", label="GitHub Vagas BR")
                            if is_rl:
                                logger.info("GitHub Vagas (%s) atingiu rate limit (%s); ativando pausa até reset.", repo, ex)
                                _mark_github_rate_limit(getattr(ex, "headers", None))
                                if etag_entry and isinstance(etag_entry[1], list):
                                    items = etag_entry[1]
                                else:
                                    break
                            else:
                                logger.warning("Falha ao sincronizar GitHub Vagas (%s): %s", repo, ex)
                                continue
                    except Exception as ex:
                        logger.warning("Falha ao sincronizar GitHub Vagas (%s): %s", repo, ex)
                        is_rl = self._record_fetch_error(ex, _status_out, portal="github-vagas", label="GitHub Vagas BR")
                        if is_rl:
                            _mark_github_rate_limit(None)
                            break
                        continue

            if not isinstance(items, list):
                continue

            for it in items:
                if not isinstance(it, dict) or "pull_request" in it:
                    continue
                created = str(it.get("created_at") or "")[:10]
                if created and created < cutoff:
                    continue
                body = str(it.get("body") or "").strip()
                if not body:
                    continue
                title = str(it.get("title") or "Vaga GitHub BR").strip()
                if re.match(r"^(?:question\s+about|d[úu]vida\s+sobre|how\s+to)\b", title, re.IGNORECASE):
                    continue
                labels = [str(l.get("name") or "") for l in (it.get("labels") or []) if isinstance(l, dict)]
                work_model, location = infer_work_model_and_location(title, body, labels=labels, default_location="Brasil")
                issue_url = str(it.get("html_url") or "").strip()
                if not issue_url:
                    continue
                author = str((it.get("user") or {}).get("login") or repo.split("/")[0])

                if self._upsert_collected_post(
                    title=title,
                    company=f"{repo} ({author})",
                    portal="github-vagas",
                    url=issue_url,
                    location=location,
                    work_model=work_model,
                    published_date=created or None,
                    description=body,
                    cv_keywords=cv_keywords,
                    extra_text=" ".join(labels),
                    match_tokens=tokens,
                    collected_urls=_collected_urls,
                    matched_post_ids=_matched_post_ids,
                    status_out=_status_out,
                ):
                    synced += 1
        return synced

    def sync_from_remotive(
        self,
        query: Optional[str] = None,
        cache_ttl_seconds: int = DEFAULT_FEED_CACHE_TTL,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
        _matched_post_ids: Optional[Set[int]] = None,
    ) -> int:
        """Scan public Remotive remote jobs feed for listings exposing direct contact emails."""
        cv_keywords = get_all_cv_keywords()
        tokens = tokenize_search_keywords([q.strip() for q in (query or "").split(",") if q.strip()])
        jobs = self._get_cached_feed("remotive:software", cache_ttl_seconds)
        if jobs is None:
            try:
                api_url = "https://remotive.com/api/remote-jobs?limit=60"
                req = urllib.request.Request(api_url, headers={"User-Agent": "vagamundo/1.0"})
                with urllib.request.urlopen(req, timeout=7) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                jobs = payload.get("jobs") or []
                if isinstance(jobs, list):
                    self._set_cached_feed("remotive:software", jobs)
            except Exception as ex:
                logger.warning("Falha ao sincronizar Remotive API: %s", ex)
                self._record_fetch_error(ex, _status_out, portal="remotive-search", label="Remotive")
                return 0

        synced = 0
        for item in jobs or []:
            if not isinstance(item, dict):
                continue
            desc = html_to_text(str(item.get("description") or ""))
            if not desc:
                continue
            job_url = str(item.get("url") or "").strip() or None
            title = str(item.get("title") or "Remote Opportunity").strip()
            company = str(item.get("company_name") or "Remotive Company").strip()
            loc = str(item.get("candidate_required_location") or "Remoto / Global").strip()
            pub = str(item.get("publication_date") or "")[:10] or None
            tags = " ".join(str(t) for t in (item.get("tags") or []))
            if self._upsert_collected_post(
                title=title,
                company=company,
                portal="remotive-search",
                url=job_url,
                location=loc,
                work_model="remoto",
                published_date=pub,
                description=desc,
                cv_keywords=cv_keywords,
                extra_text=tags,
                match_tokens=tokens,
                collected_urls=_collected_urls,
                matched_post_ids=_matched_post_ids,
                status_out=_status_out,
            ):
                synced += 1
        return synced

    def sync_from_recent_scrapes(
        self,
        query: Optional[str] = None,
        max_files: int = 3,
        _collected_urls: Optional[Set[str]] = None,
        _matched_post_ids: Optional[Set[int]] = None,
        _status_out: Optional[dict] = None,
    ) -> int:
        """Mine direct emails from recent painel_busca_*.json caches without re-importing discarded URLs."""
        pattern = os.path.join(tempfile.gettempdir(), "painel_busca_*.json")
        files = sorted(glob.glob(pattern))[-max_files:]
        if not files:
            return 0

        cv_keywords = get_all_cv_keywords()
        tokens = tokenize_search_keywords([q.strip() for q in (query or "").split(",") if q.strip()])
        synced = 0
        seen_urls: Set[str] = set()

        for path in reversed(files):
            try:
                payload = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read search cache %s: %s", path, exc)
                continue
            for item in payload.get("new") or []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                with self._repo_lock:
                    existing_job = self.repo.get_job_by_url(url)
                if existing_job and existing_job.get("status") in EXCLUDED_RADAR_JOB_STATUSES:
                    continue
                desc = str(item.get("description") or "").strip()
                if not desc:
                    continue
                if self._upsert_collected_post(
                    title=str(item.get("title") or "Oportunidade"),
                    company=str(item.get("company") or "Empresa"),
                    portal=str(item.get("portal") or "jobs"),
                    url=url,
                    location=str(item.get("location") or "Brasil"),
                    work_model=item.get("work_model"),
                    published_date=item.get("posted_date") or item.get("date"),
                    description=desc,
                    cv_keywords=cv_keywords,
                    job_id=existing_job.get("id") if existing_job else None,
                    match_tokens=tokens,
                    collected_urls=_collected_urls,
                    matched_post_ids=_matched_post_ids,
                    status_out=_status_out,
                ):
                    synced += 1
        return synced

    @staticmethod
    def _preferred_freehire_country() -> str:
        """Infer default ISO2 country for freehire-search from candidate answers, defaulting to BR."""
        try:
            from backend.tools import painel_perfil

            answers = painel_perfil.load_answers()
            loc_text = f"{answers.get('cidade', '')} {answers.get('locais', '')}".lower()
        except (ImportError, OSError, AttributeError):
            return "BR"

        country_hints = (
            (("estados unidos", "united states", "eua", "usa"), "US"),
            (("portugal", "lisboa", "porto"), "PT"),
            (("canada", "canadá", "toronto", "vancouver"), "CA"),
            (("reino unido", "united kingdom", "uk", "london", "londres"), "GB"),
            (("alemanha", "germany", "berlin", "berlim", "munich"), "DE"),
            (("espanha", "spain", "madrid", "barcelona"), "ES"),
        )
        if not any(tok in loc_text for tok in ("brasil", "brazil", "sao paulo", "são paulo", "belo horizonte", "rio de janeiro", "campinas", "curitiba")):
            for tokens, code in country_hints:
                if any(tok in loc_text for tok in tokens):
                    return code
        return "BR"

    @staticmethod
    def _build_live_portal_calls(portal: str, clean_term: str, target_country: str) -> List[List[str]]:
        if portal == "freehire-search":
            return [
                ["-q", clean_term, "--country", target_country, "--format", "json"],
                ["-q", clean_term, "--remote", "--format", "json"],
                ["-q", clean_term, "--limit", "50", "--format", "json"],
            ]
        extra_args = list((LIVE_PORTAL_SPECS.get(portal) or {}).get("extra_args") or ())
        return [["-q", clean_term, *extra_args, "--format", "json"]]

    def sync_from_live_portals(
        self,
        terms: List[str],
        cache_ttl_seconds: int = DEFAULT_FEED_CACHE_TTL,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
        _matched_post_ids: Optional[Set[int]] = None,
        country: Optional[str] = None,
    ) -> int:
        """Query email-rich installed portal CLIs with session caching."""
        installed = scrape_run.installed_portals()
        live_portals = _facade_attr("RECRUITER_LIVE_PORTALS", RECRUITER_LIVE_PORTALS)
        active_portals = [p for p in live_portals if installed.get(p)]
        if not active_portals or not terms:
            return 0

        cv_keywords = get_all_cv_keywords()
        tokens = tokenize_search_keywords(terms)
        synced = 0
        target_country = (country or self._preferred_freehire_country()).upper()

        tasks: List[Tuple[str, List[str], str]] = []
        for term in terms[:2]:
            clean_term = ROLE_PREFIX_RE.sub("", term.strip()).strip() or term.strip()
            for portal in active_portals:
                for cargs in self._build_live_portal_calls(portal, clean_term, target_country):
                    cache_key = f"portal:{portal}:{' '.join(cargs).lower()}"
                    tasks.append((portal, cargs, cache_key))

        to_fetch = [(p, ca, ck) for (p, ca, ck) in tasks if self._get_cached_feed(ck, cache_ttl_seconds) is None]
        if to_fetch:
            def _fetch_one(item: Tuple[str, List[str], str]) -> Tuple[str, List[str], str, Any, Optional[str]]:
                p, ca, ck = item
                try:
                    res, err = scrape_run.run_cli(p, ca, timeout=30)
                except TypeError:
                    res, err = scrape_run.run_cli(p, ca)
                return p, ca, ck, res, err

            with ThreadPoolExecutor(max_workers=min(8, len(to_fetch))) as pool:
                for p, _ca, ck, res, err in pool.map(_fetch_one, to_fetch):
                    if err:
                        err_l = err.lower()
                        if _status_out is not None:
                            with self._health_lock, _HEALTH_SYNC_LOCK:
                                _status_out["errors"] = int(_status_out.get("errors", 0)) + 1
                                is_rl = any(tok in err_l for tok in ("429", "403", "rate", "too many", "blocked"))
                                if is_rl:
                                    _status_out["rate_limited"] = True
                                by_portal = _status_out.setdefault("by_portal", {})
                                entry = by_portal.setdefault(p, {"fetched": 0, "matched": 0, "errors": 0, "last_error": None})
                                entry["errors"] = int(entry.get("errors", 0)) + 1
                                entry["last_error"] = err[:140]
                                human = str((LIVE_PORTAL_SPECS.get(p) or {}).get("label") or p)
                                warn_msg = (
                                    f"{human} atingiu limite temporário de acesso"
                                    if is_rl
                                    else f"Falha parcial ao consultar {human}"
                                )
                                warnings = _status_out.setdefault("warnings", [])
                                if warn_msg not in warnings:
                                    warnings.append(warn_msg)
                        continue
                    self._set_cached_feed(ck, res or [])

        seen_portal_urls: Set[Tuple[str, str]] = set()
        for portal, _cargs, cache_key in tasks:
            rows = self._get_cached_feed(cache_key, cache_ttl_seconds)
            if not rows:
                continue
            spec = LIVE_PORTAL_SPECS.get(portal) or {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or row.get("apply_url") or "").strip() or None
                if url:
                    dedup_key = (portal, url)
                    if dedup_key in seen_portal_urls:
                        continue
                    seen_portal_urls.add(dedup_key)
                    with self._repo_lock:
                        existing_job = self.repo.get_job_by_url(url)
                    if existing_job and existing_job.get("status") in EXCLUDED_RADAR_JOB_STATUSES:
                        continue
                else:
                    existing_job = None
                desc = str(row.get("description") or "").strip()
                if not desc:
                    continue
                if portal == "remotar-search":
                    default_loc = "Remoto / Internacional" if row.get("international") else "Brasil"
                else:
                    default_loc = str(spec.get("default_location") or "Global")
                if self._upsert_collected_post(
                    title=str(row.get("title") or "Oportunidade"),
                    company=str(row.get("company") or "Empresa"),
                    portal=portal,
                    url=url,
                    location=str(row.get("location") or default_loc),
                    work_model=row.get("work_model") or row.get("workplace_type"),
                    published_date=row.get("posted_date") or row.get("date"),
                    description=desc,
                    cv_keywords=cv_keywords,
                    job_id=existing_job.get("id") if existing_job else None,
                    match_tokens=tokens,
                    collected_urls=_collected_urls,
                    matched_post_ids=_matched_post_ids,
                    status_out=_status_out,
                ):
                    synced += 1
        return synced

    @staticmethod
    def _call_sync_source(
        fn: Callable[..., Any],
        *args: Any,
        status_out: Optional[dict] = None,
        matched_post_ids: Optional[Set[int]] = None,
        **kwargs: Any,
    ) -> Any:
        call_kwargs = dict(kwargs)
        side_effect = getattr(fn, "side_effect", None)
        inspect_target = (
            side_effect
            if callable(side_effect)
            and not (isinstance(side_effect, type) and issubclass(side_effect, BaseException))
            else fn
        )
        try:
            sig = inspect.signature(inspect_target)
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            params = sig.parameters
        except (TypeError, ValueError):
            has_var_kw = True
            params = {}

        if status_out is not None and (has_var_kw or "_status_out" in params):
            call_kwargs["_status_out"] = status_out
        if matched_post_ids is not None and (has_var_kw or "_matched_post_ids" in params):
            call_kwargs["_matched_post_ids"] = matched_post_ids
        if "query" in call_kwargs and not (has_var_kw or "query" in params):
            call_kwargs.pop("query")
        if "max_age_days" in call_kwargs and not (has_var_kw or "max_age_days" in params):
            call_kwargs.pop("max_age_days")
        return fn(*args, **call_kwargs)

    def sync_all(
        self,
        query: Optional[str] = None,
        *,
        should_stop: Optional[Callable[[], bool]] = None,
        days: Optional[int] = None,
    ) -> dict:
        """Scan local jobs, recent caches, BR GitHub boards, Remotive, live portals and HN in parallel."""
        matched_post_ids: Set[int] = set()
        health: dict = {"rate_limited": False, "errors": 0, "by_portal": {}, "warnings": []}
        res = self._call_sync_source(
            self.sync_from_jobs,
            query=query,
            status_out=health,
            matched_post_ids=matched_post_ids,
        )
        hn_urls: Set[str] = set()
        extra_urls: Set[str] = set()
        collected_post_ids: Set[int] = set()

        terms: List[str] = []
        seen_terms: Set[str] = set()
        for raw_t in (query or "").split(","):
            t = raw_t.strip()
            if t and t.lower() not in seen_terms:
                seen_terms.add(t.lower())
                terms.append(t)

        def _run_hn() -> int:
            for term in terms[:2]:
                if should_stop and should_stop():
                    break
                hn_term = ROLE_PREFIX_RE.sub("", term).strip() or term
                self._call_sync_source(
                    self.sync_from_hn,
                    hn_term,
                    _collected_urls=hn_urls,
                    status_out=health,
                    matched_post_ids=matched_post_ids,
                )
            return len(hn_urls)

        tasks: List[Tuple[str, Callable[[], int]]] = []
        if self.enable_live_feeds:
            if terms[:2]:
                tasks.append(("hn", _run_hn))
            tasks.append((
                "scrapes",
                lambda: self._call_sync_source(
                    self.sync_from_recent_scrapes,
                    query=query,
                    _collected_urls=extra_urls,
                    status_out=health,
                    matched_post_ids=matched_post_ids,
                ),
            ))
            gh_kwargs: Dict[str, Any] = {
                "query": query,
                "_collected_urls": extra_urls,
                "status_out": health,
                "matched_post_ids": matched_post_ids,
            }
            if days is not None:
                gh_kwargs["max_age_days"] = int(days)
            tasks.append((
                "github",
                lambda: self._call_sync_source(
                    self.sync_from_github_repos,
                    **gh_kwargs,
                ),
            ))
            tasks.append((
                "remotive",
                lambda: self._call_sync_source(
                    self.sync_from_remotive,
                    query=query,
                    _collected_urls=extra_urls,
                    status_out=health,
                    matched_post_ids=matched_post_ids,
                ),
            ))
            if terms:
                tasks.append((
                    "portals",
                    lambda: self._call_sync_source(
                        self.sync_from_live_portals,
                        terms,
                        _collected_urls=extra_urls,
                        status_out=health,
                        matched_post_ids=matched_post_ids,
                    ),
                ))

        counts: Dict[str, int] = {
            "github": 0,
            "remotive": 0,
            "scrapes": 0,
            "portals": 0,
        }
        if tasks:
            with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                futures = {pool.submit(fn): key for key, fn in tasks}
                for fut, key in futures.items():
                    try:
                        val = int(fut.result() or 0)
                        if key in counts:
                            counts[key] = val
                    except Exception as exc:
                        logger.warning("Falha na fonte '%s' durante sync_all: %s", key, exc)
                        with self._health_lock, _HEALTH_SYNC_LOCK:
                            health["errors"] = int(health.get("errors", 0)) + 1

        hn_synced = len(hn_urls)
        github_synced = counts["github"]
        remotive_synced = counts["remotive"]
        scrapes_synced = counts["scrapes"]
        portal_synced = counts["portals"]
        collected_urls = hn_urls | extra_urls
        res["hn_synced"] = hn_synced
        res["hn_urls"] = sorted(hn_urls)
        res["github_synced"] = github_synced
        res["remotive_synced"] = remotive_synced
        res["scrapes_synced"] = scrapes_synced
        res["portal_synced"] = portal_synced
        res["collected_urls"] = sorted(collected_urls)
        res["collected_post_ids"] = sorted(collected_post_ids)
        res["matched_post_ids"] = sorted(matched_post_ids | collected_post_ids)
        res["portal_breakdown"] = health.get("by_portal") or {}
        res["warnings"] = list(health.get("warnings") or [])
        res["rate_limited"] = bool(health["rate_limited"])
        res["errors"] = int(health["errors"])
        res["synced"] += hn_synced + github_synced + remotive_synced + scrapes_synced + portal_synced
        return res
