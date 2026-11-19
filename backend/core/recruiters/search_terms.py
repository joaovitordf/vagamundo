"""Whitelabel bilingual search-term expansion (PT <-> EN) backed by the configured AI provider with in-memory caching."""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from typing import Any, Dict, Optional

from backend.core.recruiters.parser import strip_accents
from backend.tools import ai_providers

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_EXPANSION_CACHE: Dict[str, Dict[str, Any]] = {}
_MAX_CACHE_ENTRIES = 500

_SYSTEM_INSTRUCTION = (
    "You normalize job-search keywords between Portuguese (Brazil) and English for LinkedIn job searches. "
    "Respond ONLY with a valid JSON object using the exact schema {\"en\": string|null, \"pt\": string|null}. "
    "Return the single most standard market term in each language (1 to 4 words, no quotes, no Boolean operators). "
    "If the term is already a universal proper noun, programming language, tool, acronym or framework "
    "(such as Python, SAP, Kubernetes, Excel, BIM, AutoCAD), return null for the unchanged equivalent. "
    "Never invent unrelated skills or explanations."
)

_FORBIDDEN_OUTPUT_RE = re.compile(r"\b(?:AND|OR|NOT)\b|[()\"'{}[\];\r\n]", re.IGNORECASE)


def _resolve_ai_providers() -> Any:
    mod = sys.modules.get("backend.core.recruiter_service")
    return getattr(mod, "ai_providers", ai_providers) if mod is not None else ai_providers


def _normalize_cache_key(term: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(term or "").strip())
    return strip_accents(cleaned).lower()


def _sanitize_variant(raw: Any, original_key: str) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    cleaned = re.sub(r"\s+", " ", raw.strip()).strip(".,:-/|\"'()")
    if not cleaned or len(cleaned) < 2 or len(cleaned) > 55:
        return None
    if len(cleaned.split()) > 5:
        return None
    if _FORBIDDEN_OUTPUT_RE.search(cleaned):
        return None
    if _normalize_cache_key(cleaned) == original_key:
        return None
    return cleaned


def _parse_json_object(raw_text: str) -> Dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def clear_search_term_cache() -> None:
    """Clear the in-memory bilingual term cache (used mainly in tests)."""
    with _CACHE_LOCK:
        _EXPANSION_CACHE.clear()


def expand_search_term_with_ai(term: str) -> Dict[str, Any]:
    """Expand a single job-search keyword into its PT/EN market equivalent using the configured AI provider.

    Degrades silently when AI is unavailable, unconsented, or fails — never raises to callers.
    """
    clean_term = re.sub(r"\s+", " ", str(term or "").strip())[:100]
    if not clean_term or len(clean_term) < 2:
        return {"ok": True, "term": clean_term, "en": None, "pt": None, "source": "none"}

    # Never invoke AI on explicit Boolean expressions typed by the user.
    if re.search(r"\b(?:AND|OR|NOT)\b|[()]", clean_term):
        return {"ok": True, "term": clean_term, "en": None, "pt": None, "source": "none"}

    cache_key = _normalize_cache_key(clean_term)
    with _CACHE_LOCK:
        cached = _EXPANSION_CACHE.get(cache_key)
        if cached is not None:
            return {
                "ok": True,
                "term": clean_term,
                "en": cached.get("en"),
                "pt": cached.get("pt"),
                "source": "cache",
            }

    ap = _resolve_ai_providers()
    try:
        env = ap.load_env_file()
        if not ap.has_consent(env):
            return {"ok": True, "term": clean_term, "en": None, "pt": None, "source": "none"}
        provider = ap.get_ai_provider(env)
        if not provider or not provider.is_available():
            return {"ok": True, "term": clean_term, "en": None, "pt": None, "source": "none"}
    except Exception as exc:
        logger.debug("AI provider unavailable for search term expansion: %s", exc)
        return {"ok": True, "term": clean_term, "en": None, "pt": None, "source": "none"}

    prompt = (
        f"Job search keyword: {clean_term}\n"
        "Return JSON {\"en\": ..., \"pt\": ...} with the most common LinkedIn job-posting equivalent in English "
        "and Portuguese. Use null if the term is universal or has no distinct translation."
    )

    try:
        raw_out = provider.generate(
            prompt,
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=0.1,
            timeout=20,
            response_json=True,
        )
    except Exception as exc:
        logger.debug("AI search term expansion failed for %r: %s", clean_term, exc)
        return {"ok": True, "term": clean_term, "en": None, "pt": None, "source": "none"}

    parsed = _parse_json_object(raw_out)
    en_val = _sanitize_variant(parsed.get("en"), cache_key)
    pt_val = _sanitize_variant(parsed.get("pt"), cache_key)
    if en_val and pt_val and _normalize_cache_key(en_val) == _normalize_cache_key(pt_val):
        pt_val = None

    with _CACHE_LOCK:
        if len(_EXPANSION_CACHE) >= _MAX_CACHE_ENTRIES:
            _EXPANSION_CACHE.pop(next(iter(_EXPANSION_CACHE)), None)
        _EXPANSION_CACHE[cache_key] = {"en": en_val, "pt": pt_val}

    return {
        "ok": True,
        "term": clean_term,
        "en": en_val,
        "pt": pt_val,
        "source": "ai",
    }
