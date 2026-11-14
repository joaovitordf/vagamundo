"""Service for mining, matching and managing recruiter publications with direct emails."""

from __future__ import annotations
import glob
import hashlib
import html
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.core.constants import atomic_write_json
from backend.db.repository import Repository
from backend.tools import ai_providers, painel, painel_ia, scrape_run
from backend.tools.painel_perfil import extract_cv_areas

logger = logging.getLogger(__name__)
_HEALTH_SYNC_LOCK = threading.RLock()

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
    "accommodations@", "accomodations@", "accommodation@",
    "candidateaccommodations@", "applicantaccommodations@", "hiringaccommodation@",
    "accessibleinterviewing@", "accessibility@", "dataprotection@", "gdpr@",
    "privacidade@", "securityreporting@", "phishing@", "eeo@",
)

RECRUITER_GITHUB_REPOS: Tuple[str, ...] = (
    "backend-br/vagas",
    "soujava/vagas-java",
    "pydevbr/vagas",
    "frontendbr/vagas",
    "phpdevbr/vagas",
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


_COMPLIANCE_CONTEXT_RE = re.compile(
    r"(?:"
    r"\breasonable\s+accommodation|"
    r"\baccommodations?\s+(?:during|to\s+apply|to\s+complete|for\s+applicants?|for\s+candidates?|in\s+the\s+(?:application|hiring|interview|selection))|"
    r"\brequires?\s+(?:an?\s+)?accommodation|"
    r"\bdue\s+to\s+a\s+disability|\bindividuals\s+with\s+disabilities|"
    r"\bassistance\s+(?:in|with|during)\s+(?:the\s+)?(?:(?:job|hiring|recruitment)\s+)?(?:appl(?:y|ying|ication(?:\s+process)?)|interview)|"
    r"\bacomoda[çc][õo]es\s+razo[áa]veis|\bpessoa\s+com\s+defici[êe]ncia\s+.*acomoda|"
    r"\brequest\s+(?:access\s+(?:to\s+)?or\s+)?deletion\s+of\s+(?:your|their)\s+(?:personal\s+)?data|"
    r"\bdeletion\s+of\s+(?:your|their)\s+(?:personal\s+)?data|"
    r"\bprocessing\s+of\s+your\s+personal\s+data|"
    r"\bexercis(?:e|ing)\s+your\s+(?:privacy|data)\s+rights|"
    r"\bunder\s+applicable\s+state\s+privacy\s+law|"
    r"\bclaiming\s+to\s+be\s+from|\brecruitment\s+scam|\breport\s+(?:the\s+|this\s+)?(?:incident|scam|fraud)|"
    r"\bphishing|\bimpersonat(?:e|ing)|\bbefore\s+taking\s+any\s+further"
    r")",
    re.IGNORECASE,
)


def _strip_accents(text: str) -> str:
    """Normalize text removing accents for fuzzy matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    ).lower()


def _is_compliance_email_occurrence(text: str, start: int, end: int) -> bool:
    """Return True when this email occurrence sits purely inside an ADA/GDPR/scam-warning clause."""
    left_bound = max(0, start - 200)
    right_bound = min(len(text), end + 95)

    # Trim at nearest sentence/newline breaks so an apply instruction nearby does not mix with compliance footers.
    left_chunk = text[left_bound:start]
    for sep in ("\n", ". ", "! ", "? "):
        idx = left_chunk.rfind(sep)
        if idx != -1:
            left_chunk = left_chunk[idx + len(sep):]

    right_chunk = text[end:right_bound]
    for sep in ("\n", ". ", "! ", "? "):
        idx = right_chunk.find(sep)
        if idx != -1:
            right_chunk = right_chunk[:idx]

    clause = re.sub(r"<[^>]+>", " ", f"{left_chunk} {right_chunk}")
    clause = re.sub(r"\s+", " ", clause).strip()
    return bool(_COMPLIANCE_CONTEXT_RE.search(clause))


_OBFUSCATED_AT_PREFIX_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*[\[\(\{]\s*(?:at|arroba|@)\s*[\]\)\}]\s*([A-Za-z0-9-]+)",
    re.IGNORECASE,
)
_OBFUSCATED_DOMAIN_DOT_RE = re.compile(
    r"(@[A-Za-z0-9.-]+)\s*[\[\(\{]\s*(?:dot|ponto)\s*[\]\)\}]\s*([A-Za-z0-9-]+)",
    re.IGNORECASE,
)


def _normalize_obfuscated_emails(text: str) -> str:
    """Restore simple obfuscations such as user [arroba] domain (ponto) com (dot) br."""
    if not text:
        return ""
    out = _OBFUSCATED_AT_PREFIX_RE.sub(r"\1@\2", text)
    while True:
        updated = _OBFUSCATED_DOMAIN_DOT_RE.sub(r"\1.\2", out)
        if updated == out:
            break
        out = updated
    return out


def extract_clean_emails(text: str) -> List[str]:
    """Find and clean all valid, non-boilerplate hiring emails in text."""
    text = _normalize_obfuscated_emails(text or "")
    if not text or "@" not in text:
        return []

    spans_by_email: Dict[str, List[Tuple[int, int]]] = {}
    ordered_emails: List[str] = []

    for match in EMAIL_REGEX.finditer(text):
        e = match.group(0).strip().rstrip(".,;:!?)(\"'>]").lower()
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

        if e not in spans_by_email:
            spans_by_email[e] = []
            ordered_emails.append(e)
        spans_by_email[e].append((match.start(), match.end()))

    # Keep an email if at least one occurrence is outside ADA/GDPR/scam compliance clauses.
    return [
        em for em in ordered_emails
        if any(not _is_compliance_email_occurrence(text, s, en) for (s, en) in spans_by_email[em])
    ]


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
    elif any(k in title_lbl for k in ("hibrido", "híbrido", "hibrida", "híbrida", "hybrid")):
        work_model = "hibrido"
    elif any(k in title_lbl for k in ("presencial", "on-site", "onsite", "in-office")) and not any(
        k in title_lbl for k in ("remoto", "remota", "remote")
    ):
        work_model = "presencial"
    elif any(k in head for k in ("remoto", "remota", "remote", "home office", "teletrabalho", "anywhere", "worldwide")):
        work_model = "remoto"
    elif any(k in head for k in ("hibrido", "híbrido", "hibrida", "híbrida", "hybrid")):
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


_LINKEDIN_ID_RE = re.compile(
    r"(?:urn:li:(?:activity|share|ugcPost):|(?:activity|share|ugcPost)-)(\d{15,20})",
    re.IGNORECASE,
)


def extract_linkedin_activity_id(value: Optional[str]) -> Optional[str]:
    """Extract numeric LinkedIn activity/share/ugcPost ID from a URL, URN or text."""
    if not value:
        return None
    m = _LINKEDIN_ID_RE.search(value)
    return m.group(1) if m else None


def extract_linkedin_snowflake_date(url_or_text: Optional[str], *, min_year: int = 2015) -> Optional[str]:
    """Decode publication date (YYYY-MM-DD) embedded in LinkedIn's Snowflake activity/share ID."""
    act_id = extract_linkedin_activity_id(url_or_text)
    if not act_id:
        return None
    try:
        ts_ms = int(act_id) >> 22
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    if dt.year < min_year or dt.date() > (date.today() + timedelta(days=1)):
        return None
    return dt.strftime("%Y-%m-%d")


_RELATIVE_AGE_RE = re.compile(
    r"^\s*(?:há\s+|ha\s+)?(\d+)\s*"
    r"(min|m|h|hr|hrs|d|dia|dias|sem|w|wk|wks|m[êe]s|meses|mo|yr|yrs|ano|anos)\b",
    re.IGNORECASE,
)


def _parse_relative_age_date(age_text: Optional[str]) -> Optional[str]:
    """Convert short LinkedIn relative timestamps ('2 h', '3 d', '1 sem') into YYYY-MM-DD."""
    raw = (age_text or "").strip()
    if not raw:
        return None
    m = _RELATIVE_AGE_RE.match(raw)
    if not m:
        return None
    val = int(m.group(1))
    unit = _strip_accents(m.group(2))
    today = date.today()
    if unit in ("min", "m", "h", "hr", "hrs"):
        return today.isoformat()
    if unit in ("d", "dia", "dias"):
        return (today - timedelta(days=min(val, 365))).isoformat()
    if unit in ("sem", "w", "wk", "wks"):
        return (today - timedelta(days=min(val * 7, 365))).isoformat()
    if unit in ("mes", "meses", "mo"):
        return (today - timedelta(days=min(val * 30, 730))).isoformat()
    if unit in ("yr", "yrs", "ano", "anos"):
        return (today - timedelta(days=min(val * 365, 1825))).isoformat()
    return None


_BATCH_PREFIX = "VAGAMUNDO_LI_BATCH_V1:"


def _parse_linkedin_batch_text(raw_batch_text: str) -> List[Dict[str, Any]]:
    """Parse bookmarklet JSON payload (VAGAMUNDO_LI_BATCH_V1:...) or multi-post text separated by '---'."""
    text = (raw_batch_text or "").strip()
    if not text:
        return []

    json_candidate: Optional[str] = None
    if text.startswith(_BATCH_PREFIX):
        json_candidate = text[len(_BATCH_PREFIX):].strip()
    elif text.startswith("{") or text.startswith("["):
        json_candidate = text

    if json_candidate is not None:
        try:
            loaded = json.loads(json_candidate)
            rows = loaded.get("posts") if isinstance(loaded, dict) else loaded
            if isinstance(rows, list):
                normalized: List[Dict[str, Any]] = []
                for entry in rows:
                    if not isinstance(entry, dict):
                        continue
                    body = str(entry.get("raw_text") or entry.get("text") or "").strip()
                    if not body:
                        continue
                    normalized.append({
                        "raw_text": body,
                        "url": str(entry.get("url") or "").strip() or None,
                        "title": str(entry.get("title") or "").strip() or None,
                        "company": str(entry.get("company") or entry.get("author") or "").strip() or None,
                        "location": str(entry.get("location") or "").strip() or None,
                        "work_model": str(entry.get("work_model") or "").strip() or None,
                        "published_date": str(entry.get("published_date") or "").strip() or None,
                    })
                return normalized
        except json.JSONDecodeError:
            if text.startswith(_BATCH_PREFIX):
                raise ValueError("Payload do lote do LinkedIn está malformado ou incompleto.")

    # Fallback: multiple manually pasted posts separated by '---' line
    chunks = [c.strip() for c in re.split(r"\r?\n\s*-{3,}\s*\r?\n", text) if c.strip()]
    return [{"raw_text": chunk} for chunk in chunks]


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

    def __init__(
        self,
        repo: Repository,
        enable_live_feeds: bool = True,
        cache_dir: Optional[Path] = None,
        linkedin_worker: Optional[Any] = None,
    ):
        self.repo = repo
        self.enable_live_feeds = enable_live_feeds
        self.linkedin_worker: Optional[Any] = linkedin_worker
        self._cache_dir: Optional[Path] = Path(cache_dir) if cache_dir else None
        self._feed_cache: Dict[str, Tuple[float, Any]] = {}
        self._github_etags: Dict[str, Tuple[str, Any]] = {}
        self._github_rate_limit_until: float = 0.0
        self._feed_lock = threading.Lock()
        self._repo_lock = threading.RLock()
        self._health_lock = threading.RLock()
        if self._cache_dir is not None:
            self._load_github_disk_cache()

    def sync_from_jobs(self) -> dict:
        """Scan jobs in repository and sync any postings containing emails."""
        with self._repo_lock:
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

            with self._repo_lock:
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
                stored_wall = now_wall - max(0.0, now_mono - feed_entry[0]) if feed_entry else (now_wall - DEFAULT_FEED_CACHE_TTL)
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
        status_out: Optional[dict] = None,
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

        with self._repo_lock:
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
        is_match = True
        if match_tokens:
            hay = _strip_accents(f"{title} {company} {extra_text} {description}")
            is_match = any(tok in hay for tok in match_tokens)
        if collected_urls is not None and url and is_match:
            with self._health_lock:
                collected_urls.add(url)
        self._record_source_hit(status_out, portal, matched=is_match)
        return True

    def sync_from_hn(
        self,
        query: str,
        limit: int = 50,
        cache_ttl_seconds: int = DEFAULT_FEED_CACHE_TTL,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
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
                    # Retrocompatibilidade com mocks mínimos que retornam hits sem 'title'
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
                        status_out=_status_out,
                    )
                    if ok:
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
    ) -> int:
        """Mine active open issues with direct emails from Brazilian tech GitHub job boards."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
        cv_keywords = get_all_cv_keywords()
        tokens = _tokenize_search_keywords([q.strip() for q in (query or "").split(",") if q.strip()])
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

        for repo in RECRUITER_GITHUB_REPOS:
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
                    status_out=_status_out,
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
                self._record_fetch_error(ex, _status_out, portal="remotive-search", label="Remotive")
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
                status_out=_status_out,
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

    def sync_from_live_portals(
        self,
        terms: List[str],
        cache_ttl_seconds: int = DEFAULT_FEED_CACHE_TTL,
        _collected_urls: Optional[Set[str]] = None,
        _status_out: Optional[dict] = None,
        country: Optional[str] = None,
    ) -> int:
        """Query email-rich installed portal CLIs (remotar, freehire, remoteok) with session caching."""
        installed = scrape_run.installed_portals()
        active_portals = [p for p in RECRUITER_LIVE_PORTALS if installed.get(p)]
        if not active_portals or not terms:
            return 0

        cv_keywords = get_all_cv_keywords()
        tokens = _tokenize_search_keywords(terms)
        synced = 0
        target_country = (country or self._preferred_freehire_country()).upper()

        tasks: List[Tuple[str, List[str], str]] = []
        for term in terms[:2]:
            clean_term = _ROLE_PREFIX_RE.sub("", term.strip()).strip() or term.strip()
            for portal in active_portals:
                if portal == "freehire-search":
                    calls_args = [
                        ["-q", clean_term, "--country", target_country, "--format", "json"],
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
                try:
                    res, err = scrape_run.run_cli(p, ca, timeout=20)
                except TypeError:
                    res, err = scrape_run.run_cli(p, ca)
                return p, ca, ck, res, err

            portal_labels = {
                "remotar-search": "Remotar",
                "freehire-search": "FreeHire",
                "remoteok-search": "RemoteOK",
            }
            with ThreadPoolExecutor(max_workers=min(3, len(to_fetch))) as pool:
                for p, ca, ck, res, err in pool.map(_fetch_one, to_fetch):
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
                                human = portal_labels.get(p, p)
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

        for portal, _cargs, cache_key in tasks:
            rows = self._get_cached_feed(cache_key, cache_ttl_seconds)
            if not rows:
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or row.get("apply_url") or "").strip() or None
                if url:
                    with self._repo_lock:
                        existing_job = self.repo.get_job_by_url(url)
                    if existing_job and existing_job.get("status") in ("discarded", "applied", "skipped"):
                        continue
                else:
                    existing_job = None
                desc = str(row.get("description") or "").strip()
                if not desc:
                    continue
                if portal == "remotar-search":
                    default_loc = "Remoto / Internacional" if row.get("international") else "Brasil"
                else:
                    default_loc = "Global"
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
                    status_out=_status_out,
                ):
                    synced += 1
        return synced

    def sync_from_linkedin_browser(
        self,
        query: Optional[str] = None,
        *,
        _collected_urls: Optional[Set[str]] = None,
        _collected_post_ids: Optional[Set[int]] = None,
        _status_out: Optional[dict] = None,
        force: bool = False,
        should_stop: Optional[Callable[[], bool]] = None,
        days: Optional[int] = None,
    ) -> int:
        """Collect recruiter hiring posts via the isolated Chrome/Edge LinkedIn worker."""
        if not self.linkedin_worker:
            return 0

        search_query = (query or "").strip() or "vaga"
        if days is not None:
            try:
                res = self.linkedin_worker.search_content_posts(
                    search_query,
                    force=force,
                    should_stop=should_stop,
                    days=days,
                )
            except TypeError:
                res = self.linkedin_worker.search_content_posts(
                    search_query,
                    force=force,
                    should_stop=should_stop,
                )
        else:
            res = self.linkedin_worker.search_content_posts(
                search_query,
                force=force,
                should_stop=should_stop,
            )
        if not isinstance(res, dict):
            return 0

        if _status_out is not None:
            with self._health_lock, _HEALTH_SYNC_LOCK:
                by_portal = _status_out.setdefault("by_portal", {})
                entry = by_portal.setdefault(
                    "linkedin_post",
                    {"fetched": 0, "matched": 0, "errors": 0, "last_error": None},
                )
                skipped_reason = res.get("skipped_reason")
                _status_out["linkedin_skipped_reason"] = skipped_reason
                if res.get("cooldown_remaining_seconds") is not None:
                    _status_out["linkedin_cooldown_remaining_seconds"] = int(res.get("cooldown_remaining_seconds") or 0)
                if "cards_total" in res:
                    _status_out["linkedin_cards_total"] = int(res.get("cards_total") or 0)
                if skipped_reason in ("login_required", "checkpoint_required"):
                    msg = str(
                        res.get("error")
                        or (
                            "LinkedIn solicitou verificação/CAPTCHA na janela do navegador."
                            if skipped_reason == "checkpoint_required"
                            else "Sessão do LinkedIn expirou; reconecte na tela Recrutadores."
                        )
                    )
                    entry["last_error"] = msg[:140]
                    _status_out["linkedin_alert"] = msg
                    warnings = _status_out.setdefault("warnings", [])
                    if msg not in warnings:
                        warnings.append(msg)
                    return 0
                if not res.get("ok"):
                    err = str(res.get("error") or "").strip()
                    if err:
                        entry["errors"] = int(entry.get("errors", 0)) + 1
                        entry["last_error"] = err[:140]
                        warnings = _status_out.setdefault("warnings", [])
                        warn_msg = f"Falha parcial ao consultar LinkedIn: {err[:100]}"
                        if warn_msg not in warnings:
                            warnings.append(warn_msg)
                    return 0
                entry["last_error"] = None

        posts = res.get("posts") or []
        if not posts:
            return 0

        if _status_out is not None:
            with self._health_lock, _HEALTH_SYNC_LOCK:
                by_portal = _status_out.setdefault("by_portal", {})
                entry = by_portal.setdefault(
                    "linkedin_post",
                    {"fetched": 0, "matched": 0, "errors": 0, "last_error": None},
                )
                entry["fetched"] = int(entry.get("fetched", 0)) + len(posts)

        try:
            batch_res = self.add_pasted_posts_batch(posts, allow_without_email=False)
        except ValueError:
            return 0

        saved_posts = batch_res.get("posts") or []
        with self._health_lock, _HEALTH_SYNC_LOCK:
            for p in saved_posts:
                u = p.get("url")
                if _collected_urls is not None and u:
                    _collected_urls.add(str(u))
                pid = p.get("id")
                if _collected_post_ids is not None and pid is not None:
                    _collected_post_ids.add(int(pid))

            if _status_out is not None:
                by_portal = _status_out.setdefault("by_portal", {})
                entry = by_portal.setdefault(
                    "linkedin_post",
                    {"fetched": 0, "matched": 0, "errors": 0, "last_error": None},
                )
                entry["matched"] = int(entry.get("matched", 0)) + len(saved_posts)

        return int(batch_res.get("imported", 0)) + int(batch_res.get("updated", 0))

    @staticmethod
    def _call_sync_source(
        fn: Callable[..., Any],
        *args: Any,
        status_out: Optional[dict] = None,
        **kwargs: Any,
    ) -> Any:
        if status_out is not None:
            try:
                return fn(*args, _status_out=status_out, **kwargs)
            except TypeError:
                pass
        return fn(*args, **kwargs)

    def sync_all(
        self,
        query: Optional[str] = None,
        *,
        include_linkedin: bool = True,
        force_linkedin: bool = False,
        linkedin_only: bool = False,
        should_stop: Optional[Callable[[], bool]] = None,
        days: Optional[int] = None,
    ) -> dict:
        """Scan local jobs, recent caches, BR GitHub boards, Remotive, live portals, HN and LinkedIn in parallel."""
        res = {"scanned": 0, "posts_with_email": 0, "synced": 0} if linkedin_only else self.sync_from_jobs()
        hn_urls: Set[str] = set()
        extra_urls: Set[str] = set()
        collected_post_ids: Set[int] = set()
        health: dict = {"rate_limited": False, "errors": 0, "by_portal": {}, "warnings": []}

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
                hn_term = _ROLE_PREFIX_RE.sub("", term).strip() or term
                self._call_sync_source(self.sync_from_hn, hn_term, _collected_urls=hn_urls, status_out=health)
            return len(hn_urls)

        tasks: List[Tuple[str, Callable[[], int]]] = []
        if not linkedin_only:
            if self.enable_live_feeds:
                if terms[:2]:
                    tasks.append(("hn", _run_hn))
                tasks.append(("scrapes", lambda: self.sync_from_recent_scrapes(query=query, _collected_urls=extra_urls)))
                tasks.append((
                    "github",
                    lambda: self._call_sync_source(
                        self.sync_from_github_repos, query=query, _collected_urls=extra_urls, status_out=health
                    ),
                ))
                tasks.append((
                    "remotive",
                    lambda: self._call_sync_source(
                        self.sync_from_remotive, query=query, _collected_urls=extra_urls, status_out=health
                    ),
                ))
                if terms:
                    tasks.append((
                        "portals",
                        lambda: self._call_sync_source(
                            self.sync_from_live_portals, terms, _collected_urls=extra_urls, status_out=health
                        ),
                    ))

        if include_linkedin and self.linkedin_worker is not None:
            tasks.append((
                "linkedin",
                lambda: self.sync_from_linkedin_browser(
                    query=query,
                    _collected_urls=extra_urls,
                    _collected_post_ids=collected_post_ids,
                    _status_out=health,
                    force=force_linkedin,
                    should_stop=should_stop,
                    days=days,
                ),
            ))

        counts: Dict[str, int] = {
            "github": 0,
            "remotive": 0,
            "scrapes": 0,
            "portals": 0,
            "linkedin": 0,
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
        linkedin_synced = counts["linkedin"]
        collected_urls = hn_urls | extra_urls
        res["hn_synced"] = hn_synced
        res["hn_urls"] = sorted(hn_urls)
        res["github_synced"] = github_synced
        res["remotive_synced"] = remotive_synced
        res["scrapes_synced"] = scrapes_synced
        res["portal_synced"] = portal_synced
        res["linkedin_synced"] = linkedin_synced
        res["linkedin_skipped_reason"] = health.get("linkedin_skipped_reason")
        res["linkedin_alert"] = health.get("linkedin_alert")
        if "linkedin_cards_total" in health:
            res["linkedin_cards_total"] = health["linkedin_cards_total"]
        if "linkedin_cooldown_remaining_seconds" in health:
            res["linkedin_cooldown_remaining_seconds"] = health["linkedin_cooldown_remaining_seconds"]
        res["collected_urls"] = sorted(collected_urls)
        res["collected_post_ids"] = sorted(collected_post_ids)
        res["portal_breakdown"] = health.get("by_portal") or {}
        res["warnings"] = list(health.get("warnings") or [])
        res["rate_limited"] = bool(health["rate_limited"])
        res["errors"] = int(health["errors"])
        res["synced"] += hn_synced + github_synced + remotive_synced + scrapes_synced + portal_synced + linkedin_synced
        return res

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
            if not clean_url and len(text) < 40:
                raise ValueError("Publicação do LinkedIn sem link ou texto suficiente.")

        # If title not provided, infer from first non-empty line (capped at 90 chars)
        clean_title = (title or "").strip()
        if not clean_title:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            inferred_title = lines[0] if lines else "Publicação de Recrutador"
            clean_title = inferred_title[:90]

        clean_company = (company or "").strip() or "Recrutador / Empresa"

        resolved_date: Optional[str] = None
        if published_date and re.match(r"^\d{4}-\d{2}-\d{2}", str(published_date).strip()):
            resolved_date = str(published_date).strip()[:10]
        else:
            resolved_date = (
                extract_linkedin_snowflake_date(clean_url)
                or extract_linkedin_snowflake_date(text)
                or _parse_relative_age_date(posted_age_text)
            )

        inferred_wm, inferred_loc = _infer_work_model_and_location(
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
        matched_kws, score = match_cv_keywords(f"{clean_title} {text}", kws_pool)

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
        )
        with self._repo_lock:
            post_id = self.repo.upsert_recruiter_post(post_data)
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
            entries.extend(_parse_linkedin_batch_text(raw_batch_text))

        if not entries:
            raise ValueError("Nenhuma publicação válida encontrada para importar.")

        cv_keywords = get_all_cv_keywords()
        imported = 0
        updated = 0
        skipped = 0
        invalid = 0
        saved_posts: List[dict] = []

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
                    is_closed = bool(existing.get("dismissed")) or bool(existing.get("auto_promoted")) or (
                        existing.get("job_status") in ("applied", "interested", "discarded", "skipped")
                    )
                    if is_closed or existing.get("ai_evaluated_at"):
                        skipped += 1
                        continue

                    # Active untriaged duplicate: update only if URL matches cleanly and content/date improved
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
                        updated += 1
                    else:
                        skipped += 1
                    continue

                post_id = self.repo.upsert_recruiter_post(post_data)
                post_data["id"] = post_id
                saved_posts.append(post_data)
                imported += 1

        if imported == 0 and updated == 0 and skipped == 0 and invalid > 0:
            raise ValueError("Nenhum endereço de e-mail válido foi encontrado nas publicações enviadas.")

        return {
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "invalid": invalid,
            "posts": saved_posts,
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
        include_portals: Tuple[str, ...] = (),
        include_post_ids: Optional[Set[int]] = None,
        max_extra_portal_posts: int = 25,
    ) -> List[dict]:
        """Return untriaged active posts matching keywords/URLs, explicit imported IDs, or portals with email diversity."""
        all_untriaged = self.repo.list_recruiter_posts(only_untriaged=True)
        norm_kws = _tokenize_search_keywords(keywords)
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
                hay = _strip_accents(
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
                self.repo.update_job_ranking(jid, score, verdict)
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
        model_used = (ai_model or "").strip() or painel_ia.get_active_model_name()
        email_note = f" | E-mail direto: {best_email}" if best_email else ""
        full_summary = f"{summary or 'Triagem concluída.'}{email_note}".strip()
        subs = subscores if isinstance(subscores, dict) else {}

        try:
            self.repo.insert_evaluation({
                "job_id": job_id,
                "score_technical": subs.get("technical"),
                "score_experience": subs.get("experience"),
                "score_behavioral": subs.get("behavioral"),
                "score_location": location_verdict,
                "score_career": subs.get("career"),
                "score_global": int(score),
                "verdict": verdict,
                "language_gate": language_gate,
                "language_note": language_note,
                "strengths": strengths or [],
                "gaps": gaps or [],
                "report_md": full_summary,
                "ai_provider": model_used,
            })
        except sqlite3.Error as exc:
            logger.warning("Failed to record recruiter evaluation for job %s: %s", job_id, exc)

        try:
            h = hashlib.sha256(job_url.encode("utf-8")).hexdigest()[:16]
            eval_file = painel_ia.PAINEL_DIR / f"{h}_avaliacao.md"
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
                        "location_verdict": location_verdict or "PASS",
                        "language_gate": language_gate or "PASS",
                        "language_note": language_note or "",
                        "strengths": strengths or [],
                        "gaps": gaps or [],
                        "guard_alert": guard_alert or "",
                    },
                )
                eval_file.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write recruiter quick evaluation markdown for %s: %s", job_url, exc)

    def save_post_as_interested(self, post_id: int) -> dict:
        """Manually move a recruiter post to Me Interessam without auto-generating CV/Letter."""
        post = self.repo.get_recruiter_post(post_id)
        if not post:
            raise LookupError("Publicação não encontrada.")

        existing = self._find_existing_job_for_post(post)
        if existing and existing.get("status") == "applied":
            raise ValueError("Esta oportunidade já foi registrada em Minhas Candidaturas.")

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
            self._record_post_evaluation(
                job_id=jid,
                job_url=job_payload["url"],
                portal=job_payload["portal"],
                score=score,
                verdict=str(verdict or ""),
                summary=str(post.get("ai_summary") or ""),
                best_email=best_email,
                ai_model=post.get("ai_model"),
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
        if existing and existing.get("status") in ("applied", "discarded", "skipped", "interested"):
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
        env = ai_providers.load_env_file()
        if not ai_providers.has_consent(env):
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
        )
        if requested_ids:
            candidates = [p for p in candidates if int(p.get("id") or -1) in requested_ids]

        candidates.sort(
            key=lambda p: (
                _PORTAL_PRIORITY.get(str(p.get("portal") or ""), 2),
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

        batch_by_id = {int(p["id"]): p for p in batch if p.get("id") is not None}

        for pid, res in results:
            cls = res["classification"]
            score = int(res["score"])
            verdict = res["verdict"]
            summary = res["summary"]
            best_email = res["best_email"]
            ai_model = res.get("ai_model")
            post_obj = batch_by_id.get(int(pid)) or {}
            is_linkedin_post = post_obj.get("portal") == "linkedin_post"
            is_talent_pool = cls == "banco_talentos"
            auto_dismiss = is_talent_pool and not is_linkedin_post

            self.repo.update_recruiter_post_ai(
                pid,
                cls,
                score,
                verdict,
                summary,
                best_email,
                auto_dismissed=auto_dismiss,
                ai_model=ai_model,
            )
            if is_talent_pool:
                talent_pools_discarded += 1
            elif cls == "nao_e_vaga":
                not_a_job += 1
            else:
                active_jobs += 1

            refreshed = self.repo.get_recruiter_post(pid)
            if refreshed and (not auto_dismiss):
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

    def dismiss_post(self, post_id: int) -> bool:
        """Dismiss a recruiter post."""
        return self.repo.dismiss_recruiter_post(post_id)

    def dismiss_posts(self, post_ids: list[int]) -> list[int]:
        """Dismiss multiple recruiter posts to Limbo."""
        return self.repo.dismiss_recruiter_posts(post_ids)
