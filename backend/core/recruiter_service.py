"""Service for mining, matching and managing recruiter publications with direct emails."""

from __future__ import annotations
import html
import json
import logging
import re
import unicodedata
import urllib.parse
import urllib.request
from typing import Any, List, Set, Tuple, Optional

from backend.db.repository import Repository
from backend.tools.painel_perfil import extract_cv_areas

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Domains to ignore (test, fake, trackers, libraries)
IGNORE_DOMAINS: Set[str] = {
    "example.com", "example.org", "domain.com", "placeholder.com",
    "sentry.io", "w3.org", "schema.org", "w3c.org", "github.com",
    "git.io", "gitlab.com", "localhost", "test.com", "invalid.com"
}

# Prefixes that represent automated, abuse or compliance mailboxes
IGNORE_PREFIXES: Tuple[str, ...] = (
    "privacy@", "dpo@", "lgpd@", "noreply@", "no-reply@", "abuse@",
    "postmaster@", "security@", "mailer-daemon@", "adresprivacy@"
)


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


class RecruiterService:
    """Encapsulates business operations for recruiter posts radar."""

    def __init__(self, repo: Repository):
        self.repo = repo

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

            post_data = {
                "emails": emails,
                "email_context": context,
                "title": j.get("title") or "Oportunidade",
                "company": j.get("company") or "Empresa",
                "portal": j.get("portal") or "jobs",
                "url": j.get("url"),
                "location": j.get("location"),
                "work_model": j.get("work_model"),
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

    def sync_from_hn(self, query: str, limit: int = 20) -> int:
        """Search Hacker News Who is Hiring thread for comments containing direct emails."""
        if not query or not query.strip():
            return 0

        term = query.strip()
        try:
            url_story = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query=%22Who+is+hiring%22&hitsPerPage=1"
            req = urllib.request.Request(url_story, headers={"User-Agent": "vagamundo/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                story_data = json.loads(resp.read().decode("utf-8"))

            hits = story_data.get("hits") or []
            if not hits:
                return 0
            story_id = hits[0].get("objectID")
            if not story_id:
                return 0

            encoded_query = urllib.parse.quote(term)
            url_comments = f"https://hn.algolia.com/api/v1/search?tags=comment,story_{story_id}&query={encoded_query}&hitsPerPage={limit}"
            req_c = urllib.request.Request(url_comments, headers={"User-Agent": "vagamundo/1.0"})
            with urllib.request.urlopen(req_c, timeout=6) as resp_c:
                comments_data = json.loads(resp_c.read().decode("utf-8"))

            comment_hits = comments_data.get("hits") or []
            cv_keywords = get_all_cv_keywords()
            synced = 0

            for c in comment_hits:
                raw_html = c.get("comment_text") or ""
                text = re.sub(r"<[^>]+>", " ", raw_html)
                text = html.unescape(text).strip()
                emails = extract_clean_emails(text)
                if not emails:
                    continue

                obj_id = c.get("objectID")
                hn_url = f"https://news.ycombinator.com/item?id={obj_id}"
                author = c.get("author") or "Recrutador HN"
                created_at = (c.get("created_at") or "")[:10]

                lines = [l.strip() for l in text.splitlines() if l.strip()]
                first_line = lines[0] if lines else "Oportunidade Hacker News"
                title = first_line[:70]

                primary_email = emails[0]
                context = extract_email_context(text, primary_email)
                matched_kws, score = match_cv_keywords(f"{title} {text}", cv_keywords)

                post_data = {
                    "emails": emails,
                    "email_context": context,
                    "title": title,
                    "company": f"{author} (Hacker News)",
                    "portal": "hn-search",
                    "url": hn_url,
                    "location": "Remoto / Global",
                    "work_model": "remoto",
                    "published_date": created_at,
                    "description": text,
                    "matched_keywords": matched_kws,
                    "match_score": score,
                    "job_id": None,
                }
                self.repo.upsert_recruiter_post(post_data)
                synced += 1

            return synced
        except Exception as ex:
            logger.warning("Falha ao sincronizar comentários do Hacker News: %s", ex)
            return 0

    def sync_all(self, query: Optional[str] = None) -> dict:
        """Scan local jobs and optionally search Hacker News for live hiring posts."""
        res = self.sync_from_jobs()
        hn_synced = 0
        if query and query.strip():
            # If comma-separated, try the first specific technical keyword
            first_term = [t.strip() for t in query.split(",") if t.strip()]
            if first_term:
                hn_synced = self.sync_from_hn(first_term[0])
        res["hn_synced"] = hn_synced
        res["synced"] += hn_synced
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
    ) -> List[dict]:
        """List active recruiter posts."""
        return self.repo.list_recruiter_posts(query=query, only_cv=only_cv, portal=portal)

    def dismiss_post(self, post_id: int) -> bool:
        """Dismiss a recruiter post."""
        return self.repo.dismiss_recruiter_post(post_id)
