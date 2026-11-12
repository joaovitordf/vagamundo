"""Service for mining, matching and managing recruiter publications with direct emails."""

from __future__ import annotations
import glob
import hashlib
import html
import json
import logging
import os
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.db.repository import Repository
from backend.tools import painel, painel_ia, scrape_run
from backend.tools.painel_perfil import extract_cv_areas

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Domains to ignore (test, fake, placeholders, trackers, libraries)
IGNORE_DOMAINS: Set[str] = {
    "example.com", "example.org", "domain.com", "placeholder.com",
    "dominio.com", "dominio.com.br", "example.com.br",
    "email.com", "test.com.br", "mailinator.com",
    "sentry.io", "w3.org", "schema.org", "w3c.org", "github.com",
    "git.io", "gitlab.com", "localhost", "test.com", "invalid.com"
}

# Prefixes that represent automated, abuse, placeholder or compliance mailboxes
IGNORE_PREFIXES: Tuple[str, ...] = (
    "privacy@", "dpo@", "lgpd@", "noreply@", "no-reply@", "abuse@",
    "postmaster@", "security@", "mailer-daemon@", "adresprivacy@",
    "seu-email@", "seuemail@", "nome@", "seunome@", "example@",
)

RECRUITER_GITHUB_REPOS: Tuple[str, ...] = (
    "backend-br/vagas",
    "soujava/vagas-java",
    "pydevbr/vagas",
    "frontendbr/vagas",
    "flutterbr/vagas",
    "datascience-br/vagas",
    "react-brasil/vagas",
    "qa-brasil/vagas",
)

RECRUITER_LIVE_PORTALS: Tuple[str, ...] = (
    "remotar-search",
    "freehire-search",
    "remoteok-search",
)

DEFAULT_FEED_CACHE_TTL = 1200  # 20 minutos entre reconsultas idênticas no modo contínuo

_ROLE_PREFIX_RE = re.compile(
    r"^(?:desenvolvedor(?:a)?|programador(?:a)?|engenheir[oa]|analista|developer|engineer)\s+",
    re.IGNORECASE,
)

_PORTAL_PRIORITY: Dict[str, int] = {
    "github-vagas": 5,
    "remotar-search": 4,
    "freehire-search": 4,
    "linkedin_post": 3,
    "remotive-search": 2,
    "remoteok-search": 2,
    "hn-search": 1,
}


def _strip_accents(text: str) -> str:
    """Normalize text removing accents for fuzzy matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    ).lower()


def extract_clean_emails(text: str) -> List[str]:
    """Find and clean all valid, non-boilerplate emails in text."""
    if not text or "@" not in text:
        return []

    raw_matches = EMAIL_REGEX.findall(text)
    cleaned_emails: List[str] = []
    seen: Set[str] = set()

    for m in raw_matches:
        # Strip trailing punctuation often adjacent in text
        e = m.strip().rstrip(".,;:!?)(\"'>]").lower()
        if not e or "@" not in e:
            continue

        local_part, _, domain = e.partition("@")
        if not local_part or not domain or "." not in domain:
            continue

        # Check noise domain and prefixes
        if domain in IGNORE_DOMAINS or any(e.startswith(p) for p in IGNORE_PREFIXES):
            continue

        # Ensure top-level domain is at least 2 alpha characters
        tld = domain.split(".")[-1]
        if len(tld) < 2 or not tld.isalpha():
            continue

        if e not in seen:
            seen.add(e)
            cleaned_emails.append(e)

    return cleaned_emails


def extract_email_context(text: str, email: str, window: int = 70) -> str:
    """Extract a concise excerpt around the first appearance of the email."""
    if not text or not email:
        return ""

    idx = text.lower().find(email.lower())
    if idx == -1:
        return ""

    start = max(0, idx - window)
    end = min(len(text), idx + len(email) + window)

    snippet = text[start:end]
    # Collapse multiple whitespaces and newlines
    clean_snippet = re.sub(r"\s+", " ", snippet).strip()

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{clean_snippet}{suffix}"


def get_all_cv_keywords() -> List[str]:
    """Extract unique technical keywords from candidate's profile/CV dynamically."""
    areas = extract_cv_areas()
    kw_set: Set[str] = set()
    for a in areas:
        for kw in a.get("keywords", []):
            if kw and len(kw.strip()) > 1:
                kw_set.add(kw.strip())
    # Return sorted by length descending so longer phrases match first
    return sorted(kw_set, key=lambda x: len(x), reverse=True)


def match_cv_keywords(text: str, keywords: Optional[List[str]] = None) -> Tuple[List[str], int]:
    """Match candidate CV keywords inside publication text and compute match score."""
    if not text:
        return [], 0

    if keywords is None:
        keywords = get_all_cv_keywords()

    norm_text = _strip_accents(text)
    matched: List[str] = []

    for kw in keywords:
        norm_kw = _strip_accents(kw)
        # Match using word boundaries when possible or substring
        pattern = r"\b" + re.escape(norm_kw) + r"\b"
        if re.search(pattern, norm_text):
            matched.append(kw)

    # Score: base 25 for first match + 15 for each additional, max 100
    score = 0
    if matched:
        score = min(100, 25 + (len(matched) - 1) * 15)

    return matched, score


def _html_to_text(raw_html: str) -> str:
    """Strip HTML tags and unescape entities cleanly."""
    if not raw_html:
        return ""
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_hn_candidate_seeking_post(text: str) -> bool:
    """Detect candidate self-promotion bios or job-seeker replies on HN threads."""
    if not text:
        return True
    head = text[:450]
    head_l = head.lower()
    if any(cue in head_l for cue in (
        "seeking work",
        "available for hire",
        "i am looking for",
        "i'm looking for",
        "just applied",
        "i applied",
        "looking for a role",
        "open to work",
    )):
        if "hiring" not in head_l and "we are" not in head_l and "our team" not in head_l:
            return True

    has_loc_prefix = bool(re.match(r"^(?:location\s*:|name\s*:)", head.strip(), re.IGNORECASE))
    has_candidate_fields = any(tok in head_l for tok in (
        "willing to relocate",
        "résumé",
        "resume:",
        "remote: yes",
        "technologies:",
    ))
    has_hiring_cues = any(tok in text[:900].lower() for tok in (
        "we're hiring",
        "we are hiring",
        "is hiring",
        "apply at",
        "send your",
        "hiring ",
        "our engineering",
        "open roles",
        "positions",
    ))
    return bool(has_loc_prefix and has_candidate_fields and not has_hiring_cues)


def _infer_work_model_and_location(
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
    default_location: str = "Brasil",
) -> Tuple[Optional[str], str]:
    """Infer work_model ('remoto'/'hibrido'/'presencial') and location from labels/title."""
    lbl_text = " ".join(labels or [])
    title_lbl = f"{title} {lbl_text}".lower()
    head = f"{title_lbl} {(body or '')[:400]}".lower()
    work_model: Optional[str] = None
    if re.search(r"\b(?:no\s+remote|not\s+remote|onsite\s+only|on-site\s+only|100%\s+presencial)\b", head):
        work_model = "presencial"
    elif any(k in title_lbl for k in ("hibrido", "híbrido", "hybrid")):
        work_model = "hibrido"
    elif any(k in title_lbl for k in ("presencial", "on-site", "onsite", "in-office")) and not any(
        k in title_lbl for k in ("remoto", "remote")
    ):
        work_model = "presencial"
    elif any(k in head for k in ("remoto", "remote", "home office", "teletrabalho", "anywhere", "worldwide")):
        work_model = "remoto"
    elif any(k in head for k in ("hibrido", "híbrido", "hybrid")):
        work_model = "hibrido"
    elif any(k in head for k in ("presencial", "on-site", "onsite", "in-office")):
        work_model = "presencial"

    bracket_locs = [
        m.strip()
        for m in re.findall(r"\[([^\]]{2,35})\]", title or "")
        if not re.match(r"^(?:remoto|remote|vaga|pj|clt|jr|j[úu]nior|pleno|s[êe]nior|h[íi]brido|presencial)$", m.strip(), re.IGNORECASE)
    ]
    if bracket_locs:
        return work_model, ", ".join(bracket_locs[:2])
    if work_model == "remoto" and default_location == "Brasil":
        return work_model, "Remoto / Brasil"
    return work_model, default_location


def _parse_hn_header_meta(header_line: str, body: str) -> Tuple[str, str]:
    """Extract work_model and location from an HN 'Company | Role | Location | REMOTE/ONSITE' line."""
    work_model, _ = _infer_work_model_and_location(header_line, body[:350], default_location="Remoto / Global")
    if not work_model:
        work_model = "remoto"

    parts = [p.strip() for p in (header_line or "").split("|") if p.strip()]
    loc_candidate = ""
    for part in parts[1:]:
        p_low = part.lower()
        if any(tok in p_low for tok in ("http://", "https://", "$", "€", "£", "full-time", "full time", "engineer", "developer", "scientist", "manager", "designer")):
            continue
        if any(tok in p_low for tok in ("remote", "onsite", "on-site", "hybrid", "usa", "uk", "eu", "europe", "global", "worldwide", "ca", "ny", "tx", "sf", "london", "berlin", "toronto", "austin", "boston", "new york", "san francisco")):
            loc_candidate = part[:65]
            break
    if not loc_candidate:
        if work_model == "remoto":
            loc_candidate = "Remoto / Global"
        elif len(parts) >= 3:
            loc_candidate = parts[2][:65]
        else:
            loc_candidate = "Global"
    return work_model, loc_candidate


def _tokenize_search_keywords(keywords: Optional[List[str]]) -> List[str]:
    """Build normalized match tokens without generic role prefixes like 'Desenvolvedor'."""
    tokens: List[str] = []
    seen: Set[str] = set()
    for raw in keywords or []:
        cleaned = _strip_accents(raw or "").strip()
        if not cleaned:
            continue
        stripped = _ROLE_PREFIX_RE.sub("", cleaned).strip()
        for candidate in (cleaned, stripped):
            if len(candidate) >= 2 and candidate not in seen:
                seen.add(candidate)
                tokens.append(candidate)
        for part in re.split(r"[/,+|]+", stripped or cleaned):
            p = part.strip()
            if len(p) >= 2 and p not in seen:
                seen.add(p)
                tokens.append(p)
    return tokens


class RecruiterService:
    """Encapsulates business operations for recruiter posts radar."""

    def __init__(self, repo: Repository, enable_live_feeds: bool = True):
        self.repo = repo
        self.enable_live_feeds = enable_live_feeds
        self._feed_cache: Dict[str, Tuple[float, Any]] = {}

    def sync_from_jobs(self) -> dict:
        """Scan jobs in repository and sync any postings containing emails."""
        candidates = self.repo.get_jobs_with_potential_emails()
        cv_keywords = get_all_cv_keywords()

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
            matched_kws, score = match_cv_keywords(
                f"{j.get('title', '')} {desc}",
                cv_keywords
            )

            raw_wm = j.get("work_model") or j.get("workplace_type")
            if not raw_wm:
                raw_wm, _ = _infer_work_model_and_location(
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

            self.repo.upsert_recruiter_post(post_data)
            new_count += 1

        return {
            "scanned": len(candidates),
            "posts_with_email": found_count,
            "synced": new_count
        }

    def _get_cached_feed(self, key: str, ttl_seconds: int) -> Any:
        if ttl_seconds <= 0:
            return None
        entry = self._feed_cache.get(key)
        if not entry:
            return None
        stored_at, payload = entry
        if (time.monotonic() - stored_at) <= ttl_seconds:
            return payload
        return None

    def _set_cached_feed(self, key: str, payload: Any) -> None:
        self._feed_cache[key] = (time.monotonic(), payload)

    @staticmethod
    def _record_fetch_error(exc: Exception, status_out: Optional[dict]) -> None:
        if status_out is None:
            return
        status_out["errors"] = int(status_out.get("errors", 0)) + 1
        code = getattr(exc, "code", None)
        msg = str(exc).lower()
        if code in (403, 429, 503) or "429" in msg or "rate" in msg or "too many" in msg:
            status_out["rate_limited"] = True

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
    ) -> bool:
        """Extract clean emails from description, compute CV match score and upsert if valid."""
        emails = extract_clean_emails(description)
        if not emails:
            return False

        primary_email = emails[0]
        context = extract_email_context(description, primary_email)
        matched_kws, score = match_cv_keywords(f"{title} {extra_text} {description}", cv_keywords)

        effective_wm = work_model
        if not effective_wm:
            effective_wm, _ = _infer_work_model_and_location(
                title or "",
                description or "",
                labels=[location or "", extra_text or ""],
                default_location=location or "Brasil",
            )
            if not effective_wm and portal in ("remotar-search", "remotive-search", "remoteok-search", "jobicy-search"):
                effective_wm = "remoto"

        self.repo.upsert_recruiter_post({
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
        if collected_urls is not None and url:
            if not match_tokens:
                collected_urls.add(url)
            else:
                hay = _strip_accents(f"{title} {company} {extra_text} {description}")
                if any(tok in hay for tok in match_tokens):
                    collected_urls.add(url)
        return True

    def sync_from_hn(
        self,
        query: str,
        limit: int = 50,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
    ) -> int:
        """Search Hacker News Who is Hiring threads for clean hiring posts with direct emails."""
        if not query or not query.strip():
            return 0

        term = query.strip()
        try:
            url_story = (
                "https://hn.algolia.com/api/v1/search_by_date"
                "?tags=story,author_whoishiring&query=%22Who+is+hiring%22&hitsPerPage=6"
            )
            req = urllib.request.Request(url_story, headers={"User-Agent": "vagamundo/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                story_data = json.loads(resp.read().decode("utf-8"))

            story_ids: List[str] = []
            for h in story_data.get("hits") or []:
                st_title = str(h.get("title") or "").lower()
                sid = str(h.get("objectID") or "").strip()
                if sid and "who is hiring" in st_title:
                    story_ids.append(sid)
            if not story_ids:
                # Retrocompatibilidade com mocks mínimos que retornam hits sem 'title'
                raw_sid = str(((story_data.get("hits") or [{}])[0]).get("objectID") or "").strip()
                if raw_sid:
                    story_ids.append(raw_sid)
            if not story_ids:
                return 0

            encoded_query = urllib.parse.quote(term)
            cv_keywords = get_all_cv_keywords()
            synced = 0

            for sid in story_ids[:2]:
                url_comments = (
                    f"https://hn.algolia.com/api/v1/search?tags=comment,story_{sid}"
                    f"&query={encoded_query}&hitsPerPage={limit}"
                )
                req_c = urllib.request.Request(url_comments, headers={"User-Agent": "vagamundo/1.0"})
                with urllib.request.urlopen(req_c, timeout=6) as resp_c:
                    comments_data = json.loads(resp_c.read().decode("utf-8"))

                for c in comments_data.get("hits") or []:
                    parent_id = c.get("parent_id")
                    if parent_id is not None and str(parent_id) != str(sid):
                        continue

                    text = _html_to_text(c.get("comment_text") or "")
                    if not text or _is_hn_candidate_seeking_post(text):
                        continue

                    obj_id = c.get("objectID")
                    hn_url = f"https://news.ycombinator.com/item?id={obj_id}"
                    author = c.get("author") or "Recrutador HN"
                    created_at = (c.get("created_at") or "")[:10]
                    lines = [l.strip() for l in text.splitlines() if l.strip()]
                    header_line = lines[0] if lines else "Oportunidade Hacker News"
                    title = header_line[:70]
                    hn_work_model, hn_location = _parse_hn_header_meta(header_line, text)

                    ok = self._upsert_collected_post(
                        title=title,
                        company=f"{author} (Hacker News)",
                        portal="hn-search",
                        url=hn_url,
                        location=hn_location,
                        work_model=hn_work_model,
                        published_date=created_at,
                        description=text,
                        cv_keywords=cv_keywords,
                        collected_urls=_collected_urls,
                    )
                    if ok:
                        synced += 1

                if synced >= 3:
                    break

            return synced
        except urllib.error.HTTPError as ex:
            logger.warning("Erro HTTP ao sincronizar comentários do Hacker News (%s): %s", ex.code, ex)
            self._record_fetch_error(ex, _status_out)
            return 0
        except Exception as ex:
            logger.warning("Falha ao sincronizar comentários do Hacker News: %s", ex)
            self._record_fetch_error(ex, _status_out)
            return 0

    def sync_from_github_repos(
        self,
        query: Optional[str] = None,
        max_age_days: int = 90,
        cache_ttl_seconds: int = DEFAULT_FEED_CACHE_TTL,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
    ) -> int:
        """Mine active open issues with direct emails from Brazilian tech GitHub job boards."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
        cv_keywords = get_all_cv_keywords()
        tokens = _tokenize_search_keywords([q.strip() for q in (query or "").split(",") if q.strip()])
        gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        headers = {"User-Agent": "vagamundo/1.0", "Accept": "application/vnd.github+json"}
        if gh_token:
            headers["Authorization"] = f"Bearer {gh_token}"

        synced = 0
        for repo in RECRUITER_GITHUB_REPOS:
            cache_key = f"github:{repo}"
            items = self._get_cached_feed(cache_key, cache_ttl_seconds)
            if items is None:
                try:
                    api_url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=50"
                    req = urllib.request.Request(api_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=7) as resp:
                        items = json.loads(resp.read().decode("utf-8"))
                    if isinstance(items, list):
                        self._set_cached_feed(cache_key, items)
                except Exception as ex:
                    logger.warning("Falha ao sincronizar GitHub Vagas (%s): %s", repo, ex)
                    self._record_fetch_error(ex, _status_out)
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
                work_model, location = _infer_work_model_and_location(title, body, labels=labels, default_location="Brasil")
                issue_url = str(it.get("html_url") or "").strip()
                if not issue_url:
                    continue
                author = str((it.get("user") or {}).get("login") or repo.split("/")[0])

                ok = self._upsert_collected_post(
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
                )
                if ok:
                    synced += 1
        return synced

    def sync_from_remotive(
        self,
        query: Optional[str] = None,
        cache_ttl_seconds: int = DEFAULT_FEED_CACHE_TTL,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
    ) -> int:
        """Scan public Remotive remote jobs feed for listings exposing direct contact emails."""
        cv_keywords = get_all_cv_keywords()
        tokens = _tokenize_search_keywords([q.strip() for q in (query or "").split(",") if q.strip()])
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
                self._record_fetch_error(ex, _status_out)
                return 0

        synced = 0
        for item in jobs or []:
            if not isinstance(item, dict):
                continue
            desc = _html_to_text(str(item.get("description") or ""))
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
            ):
                synced += 1
        return synced

    def sync_from_recent_scrapes(
        self,
        query: Optional[str] = None,
        max_files: int = 3,
        _collected_urls: Optional[Set[str]] = None,
    ) -> int:
        """Mine direct emails from recent painel_busca_*.json caches without re-importing discarded URLs."""
        pattern = os.path.join(tempfile.gettempdir(), "painel_busca_*.json")
        files = sorted(glob.glob(pattern))[-max_files:]
        if not files:
            return 0

        cv_keywords = get_all_cv_keywords()
        tokens = _tokenize_search_keywords([q.strip() for q in (query or "").split(",") if q.strip()])
        synced = 0
        seen_urls: Set[str] = set()

        for path in reversed(files):
            try:
                payload = json.loads(Path(path).read_text(encoding="utf-8"))
            except Exception:
                continue
            for item in payload.get("new") or []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                existing_job = self.repo.get_job_by_url(url)
                if existing_job and existing_job.get("status") in ("discarded", "applied", "skipped"):
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
                ):
                    synced += 1
        return synced

    def sync_from_live_portals(
        self,
        terms: List[str],
        cache_ttl_seconds: int = DEFAULT_FEED_CACHE_TTL,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
    ) -> int:
        """Query email-rich installed portal CLIs (remotar, freehire, remoteok) with session caching."""
        installed = scrape_run.installed_portals()
        active_portals = [p for p in RECRUITER_LIVE_PORTALS if installed.get(p)]
        if not active_portals or not terms:
            return 0

        cv_keywords = get_all_cv_keywords()
        tokens = _tokenize_search_keywords(terms)
        synced = 0

        tasks: List[Tuple[str, List[str], str]] = []
        for term in terms[:2]:
            clean_term = _ROLE_PREFIX_RE.sub("", term.strip()).strip() or term.strip()
            for portal in active_portals:
                if portal == "freehire-search":
                    calls_args = [
                        ["-q", clean_term, "--country", "BR", "--format", "json"],
                        ["-q", clean_term, "--remote", "--format", "json"],
                    ]
                else:
                    calls_args = [["-q", clean_term, "--format", "json"]]
                for cargs in calls_args:
                    cache_key = f"portal:{portal}:{' '.join(cargs).lower()}"
                    tasks.append((portal, cargs, cache_key))

        to_fetch = [(p, ca, ck) for (p, ca, ck) in tasks if self._get_cached_feed(ck, cache_ttl_seconds) is None]
        if to_fetch:
            def _fetch_one(item: Tuple[str, List[str], str]) -> Tuple[str, List[str], str, Any, Optional[str]]:
                p, ca, ck = item
                res, err = scrape_run.run_cli(p, ca)
                return p, ca, ck, res, err

            with ThreadPoolExecutor(max_workers=min(3, len(to_fetch))) as pool:
                for p, ca, ck, res, err in pool.map(_fetch_one, to_fetch):
                    if err:
                        err_l = err.lower()
                        if _status_out is not None:
                            _status_out["errors"] = int(_status_out.get("errors", 0)) + 1
                            if any(tok in err_l for tok in ("429", "rate", "too many", "blocked")):
                                _status_out["rate_limited"] = True
                        continue
                    self._set_cached_feed(ck, res or [])

        for portal, _cargs, cache_key in tasks:
            rows = self._get_cached_feed(cache_key, cache_ttl_seconds)
            if not rows:
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or row.get("apply_url") or "").strip() or None
                if url:
                    existing_job = self.repo.get_job_by_url(url)
                    if existing_job and existing_job.get("status") in ("discarded", "applied", "skipped"):
                        continue
                else:
                    existing_job = None
                desc = str(row.get("description") or "").strip()
                if not desc:
                    continue
                if self._upsert_collected_post(
                    title=str(row.get("title") or "Oportunidade"),
                    company=str(row.get("company") or "Empresa"),
                    portal=portal,
                    url=url,
                    location=str(row.get("location") or ("Brasil" if portal == "remotar-search" else "Global")),
                    work_model=row.get("work_model") or row.get("workplace_type"),
                    published_date=row.get("posted_date") or row.get("date"),
                    description=desc,
                    cv_keywords=cv_keywords,
                    job_id=existing_job.get("id") if existing_job else None,
                    match_tokens=tokens,
                    collected_urls=_collected_urls,
                ):
                    synced += 1
        return synced

    def sync_all(self, query: Optional[str] = None) -> dict:
        """Scan local jobs, recent caches, BR GitHub boards, Remotive, live portals and clean HN threads."""
        res = self.sync_from_jobs()
        hn_urls: Set[str] = set()
        extra_urls: Set[str] = set()
        health: dict = {"rate_limited": False, "errors": 0}

        terms: List[str] = []
        seen_terms: Set[str] = set()
        for raw_t in (query or "").split(","):
            t = raw_t.strip()
            if t and t.lower() not in seen_terms:
                seen_terms.add(t.lower())
                terms.append(t)

        for term in terms[:2]:
            hn_term = _ROLE_PREFIX_RE.sub("", term).strip() or term
            try:
                self.sync_from_hn(hn_term, _collected_urls=hn_urls, _status_out=health)
            except TypeError:
                self.sync_from_hn(hn_term, _collected_urls=hn_urls)

        github_synced = 0
        remotive_synced = 0
        scrapes_synced = 0
        portal_synced = 0
        if self.enable_live_feeds:
            scrapes_synced = self.sync_from_recent_scrapes(query=query, _collected_urls=extra_urls)
            github_synced = self.sync_from_github_repos(query=query, _collected_urls=extra_urls, _status_out=health)
            remotive_synced = self.sync_from_remotive(query=query, _collected_urls=extra_urls, _status_out=health)
            if terms:
                portal_synced = self.sync_from_live_portals(terms, _collected_urls=extra_urls, _status_out=health)

        hn_synced = len(hn_urls)
        collected_urls = hn_urls | extra_urls
        res["hn_synced"] = hn_synced
        res["hn_urls"] = sorted(hn_urls)
        res["github_synced"] = github_synced
        res["remotive_synced"] = remotive_synced
        res["scrapes_synced"] = scrapes_synced
        res["portal_synced"] = portal_synced
        res["collected_urls"] = sorted(collected_urls)
        res["rate_limited"] = bool(health["rate_limited"])
        res["errors"] = int(health["errors"])
        res["synced"] += hn_synced + github_synced + remotive_synced + scrapes_synced + portal_synced
        return res

    def add_pasted_post(
        self,
        raw_text: str,
        url: Optional[str] = None,
        title: Optional[str] = None,
        company: Optional[str] = None,
        location: Optional[str] = None,
        work_model: Optional[str] = None,
    ) -> dict:
        """Parse and save a manually pasted post from LinkedIn or other feed."""
        text = (raw_text or "").strip()
        if not text:
            raise ValueError("O texto da publicação não pode estar vazio.")

        emails = extract_clean_emails(text)
        if not emails:
            raise ValueError("Nenhum endereço de e-mail válido foi encontrado no texto.")

        # If title not provided, infer from first non-empty line (capped at 60 chars)
        if not title or not title.strip():
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            inferred_title = lines[0] if lines else "Publicação de Recrutador"
            title = inferred_title[:60]

        if not company or not company.strip():
            company = "Recrutador / Empresa"

        primary_email = emails[0]
        context = extract_email_context(text, primary_email)

        cv_keywords = get_all_cv_keywords()
        matched_kws, score = match_cv_keywords(f"{title} {text}", cv_keywords)

        post_data = {
            "emails": emails,
            "email_context": context,
            "title": title.strip(),
            "company": company.strip(),
            "portal": "linkedin_post",
            "url": url.strip() if url else None,
            "location": location.strip() if location else "Remoto / A Definir",
            "work_model": work_model.strip() if work_model else None,
            "published_date": None,
            "description": text,
            "matched_keywords": matched_kws,
            "match_score": score,
            "job_id": None,
        }

        post_id = self.repo.upsert_recruiter_post(post_data)
        post_data["id"] = post_id
        return post_data

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
        filtered_out: List[dict] = []
        for post in posts:
            p_portal = str(post.get("portal") or "")
            p_title = str(post.get("title") or "")
            p_desc = str(post.get("description") or "")
            if p_portal == "hn-search" and _is_hn_candidate_seeking_post(p_desc):
                continue
            if p_portal == "github-vagas" and re.match(r"^(?:question\s+about|d[úu]vida\s+sobre|how\s+to)\b", p_title, re.IGNORECASE):
                continue

            if not post.get("work_model"):
                inferred_wm, _ = _infer_work_model_and_location(
                    p_title,
                    p_desc,
                    labels=[str(post.get("location") or "")],
                )
                if not inferred_wm and p_portal in ("remotar-search", "remotive-search", "remoteok-search", "jobicy-search"):
                    inferred_wm = "remoto"
                if inferred_wm:
                    post["work_model"] = inferred_wm

            if not post.get("matched_keywords") and cv_keywords:
                kws, sc = match_cv_keywords(f"{p_title} {p_desc}", cv_keywords)
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

    def find_untriaged_candidates(
        self,
        keywords: Optional[List[str]] = None,
        include_urls: Optional[Set[str]] = None,
        max_per_email: int = 2,
    ) -> List[dict]:
        """Return untriaged active posts matching keywords/URLs, ordered by portal & CV score with email diversity."""
        all_untriaged = self.repo.list_recruiter_posts(only_untriaged=True)
        norm_kws = _tokenize_search_keywords(keywords)
        extra_urls = {str(u).strip() for u in (include_urls or set()) if str(u or "").strip()}
        if not norm_kws and not extra_urls:
            matched = list(all_untriaged)
        else:
            matched = []
            for post in all_untriaged:
                p_url = str(post.get("url") or "").strip()
                if p_url and p_url in extra_urls:
                    matched.append(post)
                    continue
                hay = _strip_accents(
                    f"{post.get('title') or ''} {post.get('company') or ''} "
                    f"{post.get('description') or ''} {' '.join(post.get('matched_keywords') or [])}"
                )
                if any(kw in hay for kw in norm_kws):
                    matched.append(post)

        # Prioriza fontes de maior aderência (GitHub Vagas BR, Remotar, FreeHire) e maior match_score prévio
        matched.sort(
            key=lambda p: (
                _PORTAL_PRIORITY.get(str(p.get("portal") or ""), 2),
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
                with self.repo.conn:
                    self.repo.conn.execute(
                        "UPDATE jobs SET rank_score = COALESCE(?, rank_score), rank_verdict = COALESCE(?, rank_verdict), rank_date = ? WHERE id = ?",
                        (
                            int(score) if score is not None else None,
                            verdict,
                            date.today().isoformat(),
                            jid,
                        ),
                    )
        else:
            jid = self.repo.upsert_job({**job_payload, "source": "recruiter_radar", "status": "new"})

        try:
            painel_ia.save_job_cache(job_url, {**job_payload, "id": jid})
        except Exception:
            pass

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

    def save_post_as_interested(self, post_id: int) -> dict:
        """Manually move a recruiter post to Me Interessam without auto-generating CV/Letter."""
        post = self.repo.get_recruiter_post(post_id)
        if not post:
            raise LookupError("Publicação não encontrada.")

        existing = self._find_existing_job_for_post(post)
        if existing and existing.get("status") == "applied":
            raise ValueError("Esta oportunidade já foi registrada em Minhas Candidaturas.")

        best_email = (post.get("ai_best_email") or ((post.get("emails") or [""])[0]) or "").strip()
        raw_score = post.get("ai_score") if post.get("ai_score") is not None else post.get("match_score")
        score = int(raw_score) if raw_score is not None and int(raw_score) > 0 else None
        verdict = post.get("ai_verdict")

        jid, job_url, _ = self._prepare_job_from_post(
            post,
            score=score,
            verdict=verdict,
            best_email=best_email,
            existing=existing,
        )

        if not existing or existing.get("status") != "interested":
            note = f"Salvo manualmente de Recrutadores ({best_email})" if best_email else "Salvo manualmente de Recrutadores"
            self.repo.mark_jobs(
                [jid],
                decision="interested",
                source="manual_recruiter",
                note=note,
            )

        with self.repo.conn:
            self.repo.conn.execute(
                "UPDATE recruiter_posts SET job_id = ?, dismissed = 0 WHERE id = ?",
                (jid, post_id),
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

        raw_score = post.get("ai_score") if post.get("ai_score") is not None else post.get("match_score")
        score = int(raw_score) if raw_score is not None and int(raw_score) > 0 else None
        jid, job_url, _ = self._prepare_job_from_post(
            post,
            score=score,
            verdict=post.get("ai_verdict"),
            best_email=target_email,
            existing=existing,
        )

        today_iso = date.today().isoformat()
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        app_notes = (notes or "").strip() or f"E-mail direto: {target_email}"

        self.repo.mark_jobs(
            [jid],
            decision="applied",
            source="recruiter_outreach",
            note=app_notes,
        )
        app_id = self.repo.upsert_application({
            "job_id": jid,
            "status": "applied",
            "applied_date": today_iso,
            "notes": app_notes,
            "contact_channel": "recruiter_email",
            "contacted_email": target_email,
            "recruiter_post_id": post_id,
        })

        company_name = post.get("company") or "Empresa"
        role_title = post.get("title") or "Cargo"
        portal_name = post.get("portal") or "recruiter_radar"
        self.repo.record_application_ledger(
            company=company_name,
            role=role_title,
            portal=portal_name,
            job_url=job_url,
            job_id=jid,
            applied_date=today_iso,
        )
        try:
            painel.record_applied(
                url=job_url,
                company=company_name,
                role=role_title,
                portal=portal_name,
            )
        except Exception:
            pass

        self.repo.mark_recruiter_post_contacted(
            post_id=post_id,
            job_id=jid,
            contacted_email=target_email,
            contacted_at=now_iso,
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
    ) -> Optional[str]:
        """Create or link a job row from a qualified recruiter post and move it to Me Interessam."""
        post_id = post["id"]
        existing = self._find_existing_job_for_post(post)
        if existing and existing.get("status") in ("applied", "discarded", "skipped", "interested"):
            return None

        email_note = f" | E-mail direto: {best_email}" if best_email else ""
        jid, job_url, job_payload = self._prepare_job_from_post(
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

        # Persist AI evaluation & cache so CV / cover-letter generation in Me Interessam works seamlessly
        try:
            self.repo.insert_evaluation({
                "job_id": jid,
                "score_global": int(score),
                "verdict": verdict,
                "strengths": [],
                "gaps": [],
                "report_md": f"{summary}{email_note}".strip(),
                "ai_provider": "antigravity",
            })
        except Exception:
            pass

        try:
            cache_url = job_payload["url"]
            h = hashlib.sha256(cache_url.encode("utf-8")).hexdigest()[:16]
            eval_file = painel_ia.PAINEL_DIR / f"{h}_avaliacao.md"
            eval_file.parent.mkdir(parents=True, exist_ok=True)
            if not eval_file.exists() or eval_file.read_text(encoding="utf-8").startswith("## Triagem rápida"):
                eval_file.write_text(
                    f"## Triagem rápida: {job_payload['portal']}\n\n"
                    f"**Nota geral: {int(score)}/100**\n"
                    f"### Veredito: {verdict}\n\n"
                    f"### Resumo da triagem rápida\n{summary}{email_note}\n\n"
                    f"URL: {cache_url}\n",
                    encoding="utf-8",
                )
        except Exception:
            pass

        self.repo.mark_recruiter_post_promoted(post_id, jid, run_id=run_id)
        return jid

    def dismiss_post(self, post_id: int) -> bool:
        """Dismiss a recruiter post."""
        return self.repo.dismiss_recruiter_post(post_id)
