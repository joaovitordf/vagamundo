"""Backwards-compatible public facade for the modularized recruiters radar package."""

from __future__ import annotations

from backend.core.recruiters.parser import (
    DEFAULT_FEED_CACHE_TTL,
    EMAIL_REGEX,
    IGNORE_DOMAINS,
    IGNORE_PREFIXES,
    RECRUITER_GITHUB_REPOS,
    RECRUITER_LIVE_PORTALS,
    extract_clean_emails,
    extract_email_context,
    extract_linkedin_activity_id,
    extract_linkedin_snowflake_date,
    get_all_cv_keywords,
    html_to_text as _html_to_text,
    infer_work_model_and_location as _infer_work_model_and_location,
    is_hn_candidate_seeking_post as _is_hn_candidate_seeking_post,
    match_cv_keywords,
    normalize_obfuscated_emails as _normalize_obfuscated_emails,
    parse_hn_header_meta as _parse_hn_header_meta,
    parse_linkedin_batch_text as _parse_linkedin_batch_text,
    parse_relative_age_date as _parse_relative_age_date,
    strip_accents as _strip_accents,
    tokenize_search_keywords as _tokenize_search_keywords,
)
from backend.core.recruiters.service import RecruiterService
from backend.tools import ai_providers  # noqa: F401 - kept at facade scope for test monkeypatching

__all__ = [
    "DEFAULT_FEED_CACHE_TTL",
    "EMAIL_REGEX",
    "IGNORE_DOMAINS",
    "IGNORE_PREFIXES",
    "RECRUITER_GITHUB_REPOS",
    "RECRUITER_LIVE_PORTALS",
    "RecruiterService",
    "ai_providers",
    "extract_clean_emails",
    "extract_email_context",
    "extract_linkedin_activity_id",
    "extract_linkedin_snowflake_date",
    "get_all_cv_keywords",
    "match_cv_keywords",
]
