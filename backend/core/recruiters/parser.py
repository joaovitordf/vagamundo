"""Text, email, LinkedIn Snowflake/batch parsing, and keyword matching helpers for recruiter posts."""

from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.tools.painel_perfil import extract_cv_areas

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Domains to ignore (test, fake, placeholders, trackers, libraries)
IGNORE_DOMAINS: Set[str] = {
    "example.com", "example.org", "domain.com", "placeholder.com",
    "dominio.com", "dominio.com.br", "example.com.br",
    "email.com", "test.com.br", "mailinator.com",
    "sentry.io", "w3.org", "schema.org", "w3c.org", "github.com",
    "git.io", "gitlab.com", "localhost", "test.com", "invalid.com",
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
    "solides-search",
    "gupy-search",
    "greenhouse-search",
    "ashby-search",
    "jobicy-search",
    "empregos-search",
)

LIVE_PORTAL_SPECS: Dict[str, Dict[str, Any]] = {
    "remotar-search": {"label": "Remotar", "default_location": "Brasil", "extra_args": ()},
    "freehire-search": {"label": "FreeHire", "default_location": "Global", "extra_args": ()},
    "remoteok-search": {"label": "RemoteOK", "default_location": "Remoto / Global", "extra_args": ()},
    "solides-search": {"label": "Sólides Vagas", "default_location": "Brasil", "extra_args": ()},
    "gupy-search": {"label": "Gupy", "default_location": "Brasil", "extra_args": ()},
    "greenhouse-search": {"label": "Greenhouse", "default_location": "Global", "extra_args": ("--with-description",)},
    "ashby-search": {"label": "Ashby", "default_location": "Global", "extra_args": ()},
    "jobicy-search": {"label": "Jobicy", "default_location": "Remoto / Global", "extra_args": ()},
    "empregos-search": {"label": "Empregos.com.br", "default_location": "Brasil", "extra_args": ("--with-description",)},
}

DEFAULT_FEED_CACHE_TTL = 1200  # 20 minutos entre reconsultas idênticas no modo contínuo

ROLE_PREFIX_RE = re.compile(
    r"^(?:desenvolvedor(?:a)?|programador(?:a)?|engenheir[oa]|analista|developer|engineer)\s+",
    re.IGNORECASE,
)

PORTAL_PRIORITY: Dict[str, int] = {
    "github-vagas": 5,
    "remotar-search": 4,
    "freehire-search": 4,
    "solides-search": 4,
    "greenhouse-search": 4,
    "gupy-search": 3,
    "ashby-search": 3,
    "linkedin_post": 3,
    "empregos-search": 2,
    "jobicy-search": 2,
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

_OBFUSCATED_AT_PREFIX_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*[\[\(\{]\s*(?:at|arroba|@)\s*[\]\)\}]\s*([A-Za-z0-9-]+)",
    re.IGNORECASE,
)
_OBFUSCATED_DOMAIN_DOT_RE = re.compile(
    r"(@[A-Za-z0-9.-]+)\s*[\[\(\{]\s*(?:dot|ponto)\s*[\]\)\}]\s*([A-Za-z0-9-]+)",
    re.IGNORECASE,
)
_LINKEDIN_ID_RE = re.compile(
    r"(?:urn:li:(?:activity|share|ugcPost):|(?:activity|share|ugcPost)-)(\d{15,20})",
    re.IGNORECASE,
)
_RELATIVE_AGE_RE = re.compile(
    r"^\s*(?:há\s+|ha\s+)?(\d+)\s*"
    r"(min|m|h|hr|hrs|d|dia|dias|sem|w|wk|wks|m[êe]s|meses|mo|yr|yrs|ano|anos)\b",
    re.IGNORECASE,
)
_BATCH_PREFIX = "VAGAMUNDO_LI_BATCH_V1:"


def strip_accents(text: str) -> str:
    """Normalize text removing accents for fuzzy matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    ).lower()


def _is_compliance_email_occurrence(text: str, start: int, end: int) -> bool:
    """Return True when this email occurrence sits purely inside an ADA/GDPR/scam-warning clause."""
    left_bound = max(0, start - 200)
    right_bound = min(len(text), end + 95)

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


def normalize_obfuscated_emails(text: str) -> str:
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
    text = normalize_obfuscated_emails(text or "")
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
        if domain in IGNORE_DOMAINS or any(e.startswith(p) for p in IGNORE_PREFIXES):
            continue

        tld = domain.split(".")[-1]
        if len(tld) < 2 or not tld.isalpha():
            continue

        if e not in spans_by_email:
            spans_by_email[e] = []
            ordered_emails.append(e)
        spans_by_email[e].append((match.start(), match.end()))

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
    clean_snippet = re.sub(r"\s+", " ", text[start:end]).strip()
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
    return sorted(kw_set, key=lambda x: len(x), reverse=True)


def match_cv_keywords(text: str, keywords: Optional[List[str]] = None) -> Tuple[List[str], int]:
    """Match candidate CV keywords inside publication text and compute match score."""
    if not text:
        return [], 0

    if keywords is None:
        keywords = get_all_cv_keywords()

    norm_text = strip_accents(text)
    matched: List[str] = []

    for kw in keywords:
        norm_kw = strip_accents(kw)
        pattern = r"\b" + re.escape(norm_kw) + r"\b"
        if re.search(pattern, norm_text):
            matched.append(kw)

    score = min(100, 25 + (len(matched) - 1) * 15) if matched else 0
    return matched, score


def html_to_text(raw_html: str) -> str:
    """Strip HTML tags and unescape entities cleanly."""
    if not raw_html:
        return ""
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_hn_candidate_seeking_post(text: str) -> bool:
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


def infer_work_model_and_location(
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
        if not re.match(
            r"^(?:remoto|remote|vaga|pj|clt|jr|j[úu]nior|pleno|s[êe]nior|h[íi]brido|presencial)$",
            m.strip(),
            re.IGNORECASE,
        )
    ]
    if bracket_locs:
        return work_model, ", ".join(bracket_locs[:2])
    if work_model == "remoto" and default_location == "Brasil":
        return work_model, "Remoto / Brasil"
    return work_model, default_location


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


def parse_relative_age_date(age_text: Optional[str]) -> Optional[str]:
    """Convert short LinkedIn relative timestamps ('2 h', '3 d', '1 sem') into YYYY-MM-DD."""
    raw = (age_text or "").strip()
    if not raw:
        return None
    m = _RELATIVE_AGE_RE.match(raw)
    if not m:
        return None
    val = int(m.group(1))
    unit = strip_accents(m.group(2))
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


def parse_linkedin_batch_text(raw_batch_text: str) -> List[Dict[str, Any]]:
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

    chunks = [c.strip() for c in re.split(r"\r?\n\s*-{3,}\s*\r?\n", text) if c.strip()]
    return [{"raw_text": chunk} for chunk in chunks]


def parse_hn_header_meta(header_line: str, body: str) -> Tuple[str, str]:
    """Extract work_model and location from an HN 'Company | Role | Location | REMOTE/ONSITE' line."""
    work_model, _ = infer_work_model_and_location(header_line, body[:350], default_location="Remoto / Global")
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


def tokenize_search_keywords(keywords: Optional[List[str]]) -> List[str]:
    """Build normalized match tokens without generic role prefixes like 'Desenvolvedor'."""
    tokens: List[str] = []
    seen: Set[str] = set()
    for raw in keywords or []:
        cleaned = strip_accents(raw or "").strip()
        if not cleaned:
            continue
        stripped = ROLE_PREFIX_RE.sub("", cleaned).strip()
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
