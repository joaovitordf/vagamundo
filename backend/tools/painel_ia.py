#!/usr/bin/env python3
"""Fachada pública e camada de provedores das tarefas de IA do painel.

Submódulos internos em `backend/tools/ia/`:
  * `context`: contexto seguro da pessoa candidata e sanitização de JSON/LaTeX;
  * `posting_reader`: coleta multi-nível, posting_guard e cache de anúncios;
  * `doc_builder`: avaliação canônica, redação LaTeX (CV/carta), perfil e entrevista;
  * `triage`: triagem rápida, classificação de posts de recrutadores e sorteio de busca.

Funciona com qualquer provedor configurado em `ai_providers` (Gemini, OpenAI/ChatGPT,
Claude, por API ou CLI). Mantém reexportação integral dos símbolos públicos e privados
para compatibilidade retroativa com callers e suítes de testes.
"""

from __future__ import annotations

import contextlib
import re
import threading
from pathlib import Path
from typing import Any

if __package__:
    from . import ai_providers, posting_guard, posting_signals, privacy_utils, rank_state
    from .ia import (
        context as _context,
        doc_builder as _doc_builder,
        posting_reader as _posting_reader,
        triage as _triage,
    )
else:
    import ai_providers
    import posting_guard
    import posting_signals
    import privacy_utils
    import rank_state
    from ia import (  # type: ignore[no-redef]
        context as _context,
        doc_builder as _doc_builder,
        posting_reader as _posting_reader,
        triage as _triage,
    )

_LLM_TLS = threading.local()

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
DOCUMENTS = ROOT / "documents"
CV_DIR = ROOT / "cv"
COVER_DIR = ROOT / "cover_letters"
INTERVIEW_DIR = ROOT / "documents" / "interview"
PAINEL_DIR = ROOT / "documents" / "applications" / "_painel"
INTERVIEW_TEMPLATE = ROOT / "templates" / "interview_template.tex"
TRACKER = ROOT / "job_search_tracker.csv"
PROFILE_MD = REPO_ROOT / ".claude" / "skills" / "job-application-assistant" / "01-candidate-profile.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# Mesmo cabeçalho do /apply e do /outcome: os três escrevem no mesmo arquivo.
TRACKER_FIELDS = [
    "date",
    "company",
    "sector",
    "role",
    "role_type",
    "channel",
    "status",
    "contact_person",
    "fit_rating",
    "notes",
    "cv_file",
    "cover_letter_file",
    "source",
    "deadline",
]

# Mapeamento de domínios para as skills portáteis em .agents/skills/
PORTAL_HOST_MAP = {
    "gupy.io": "gupy-search",
    "solides.com.br": "solides-search",
    "vagas.com.br": "vagas-search",
    "infojobs.com.br": "infojobs-search",
    "remotar.com.br": "remotar-search",
    "greenhouse.io": "greenhouse-search",
    "programathor.com.br": "programathor-search",
    "michaelpage.com.br": "michaelpage-search",
    "geekhunter.com": "geekhunter-search",
    "geekhunter.com.br": "geekhunter-search",
    "trampos.co": "trampos-search",
    "roberthalf.com": "roberthalf-search",
    "roberthalf.com.br": "roberthalf-search",
    "pcd.com.br": "pcd-search",
    "agrobase.com.br": "agrobase-search",
    "agrosearch.com.br": "agrosearch-search",
    "digai.ai": "digai-search",
    "empregos.com.br": "empregos-search",
    "linkedin.com": "linkedin-search",
    "freehire.me": "freehire-search",
    "ashbyhq.com": "ashby-search",
    "remoteok.com": "remoteok-search",
    "jobicy.com": "jobicy-search",
    "news.ycombinator.com": "hn-search",
    "hh.ru": "hh-search",
    "habr.com": "habrcareer-search",
    "career.habr.ru": "habrcareer-search",
}

FORBIDDEN_LATEX = re.compile(
    r"\\(?:input|include|includeonly|openin|openout|read|readline|write|immediate|newwrite|newread|"
    r"catcode|directlua|luaexec|special|csname|InputIfFileExists|verbatiminput|lstinputlisting)(?![A-Za-z])"
)


class ConsentRequired(ai_providers.ProviderError):
    """A pessoa ainda não confirmou o envio de dados ao provedor de IA."""


# ---------------------------------------------------------------------------
# Provedor
# ---------------------------------------------------------------------------

def get_provider_info() -> dict[str, str]:
    return ai_providers.get_ai_provider().get_info()


def is_available() -> bool:
    return ai_providers.get_ai_provider().is_available()


def get_active_model_name() -> str:
    """Return a non-empty identifier for the currently active AI model."""
    info = get_provider_info()
    model = str(info.get("model") or "").strip()
    if model and model.lower() not in ("none", "cli"):
        return model[:80]
    return str(info.get("provider") or "ia")[:80]


def _extract_ai_model(data: Any) -> str:
    """Extract the model identifier returned by the LLM JSON, falling back to the active model."""
    raw = str(data.get("model") or "").strip() if isinstance(data, dict) else ""
    if raw and raw.lower() not in ("none", "cli", "unknown", "modelo"):
        return raw[:80]
    return get_active_model_name()


@contextlib.contextmanager
def _json_mode():
    """Habilita modo JSON nativo quando o provedor ativo rodar via API HTTP."""
    prev = getattr(_LLM_TLS, "response_json", False)
    _LLM_TLS.response_json = True
    try:
        yield
    finally:
        _LLM_TLS.response_json = prev


def call_llm(
    prompt: str,
    system_instruction: str | None = None,
    temperature: float = 0.2,
    timeout: int = 180,
) -> str:
    """Despacha o pedido ao provedor escolhido em Configurações."""
    env = ai_providers.load_env_file()
    if not ai_providers.has_consent(env):
        raise ConsentRequired(
            "Antes de usar a IA, confirme em Configurações que está ciente de que o seu perfil (sem CPF nem "
            "endereço) e o texto das vagas são enviados ao provedor escolhido."
        )
    provider = ai_providers.get_ai_provider(env)
    sys_inst = ai_providers.build_system_instruction(provider, system_instruction)
    if getattr(_LLM_TLS, "response_json", False) and getattr(provider, "mode", None) == "api_key":
        return provider.generate(
            prompt, system_instruction=sys_inst, temperature=temperature, timeout=timeout, response_json=True
        )
    return provider.generate(prompt, system_instruction=sys_inst, temperature=temperature, timeout=timeout)


# ---------------------------------------------------------------------------
# Reexportações dos submódulos em tools/ia/
# ---------------------------------------------------------------------------

_read = _context._read
english_cv_text = _context.english_cv_text
candidate_profile = _context.candidate_profile
_extract_claude_profile_section = _context._extract_claude_profile_section
_compact_candidate_profile = _context._compact_candidate_profile
get_candidate_name = _context.get_candidate_name
sanitize_filename = _context.sanitize_filename
_tagged_block = _context._tagged_block
_vaga_block = _context._vaga_block
_json_object = _context._json_object
_latex_from_reply = _context._latex_from_reply

_HIGH_SIGNAL_LINE_RE = _posting_reader._HIGH_SIGNAL_LINE_RE
resolve_portal_skill = _posting_reader.resolve_portal_skill
_run = _posting_reader._run
_find_cached_job = _posting_reader._find_cached_job
save_job_cache = _posting_reader.save_job_cache
_load_candidate_triage_rules = _posting_reader._load_candidate_triage_rules
_apply_posting_guard = _posting_reader._apply_posting_guard
_compact_posting_text = _posting_reader._compact_posting_text
_prompt_posting_budget = _posting_reader._prompt_posting_budget
_format_structured_header = _posting_reader._format_structured_header
_detect_language = _posting_reader._detect_language
fetch_posting = _posting_reader.fetch_posting
_extract_meta = _posting_reader._extract_meta
_resolve_meta = _posting_reader._resolve_meta

_extract_markdown_subscores_and_gates = _doc_builder._extract_markdown_subscores_and_gates
_extract_md_section_bullets = _doc_builder._extract_md_section_bullets
extract_eval_details_from_md = _doc_builder.extract_eval_details_from_md
postprocess_avaliacao_md = _doc_builder.postprocess_avaliacao_md
avaliar_vaga = _doc_builder.avaliar_vaga
_append_tracker = _doc_builder._append_tracker
redigir_curriculo = _doc_builder.redigir_curriculo
_extract_plain_letter = _doc_builder._extract_plain_letter
redigir_carta = _doc_builder.redigir_carta
_profile_documents = _doc_builder._profile_documents
montar_perfil = _doc_builder.montar_perfil
_escape_latex = _doc_builder._escape_latex
preparar_entrevista = _doc_builder.preparar_entrevista

_CALIBRATION_ANCHORS = _triage._CALIBRATION_ANCHORS
_LOW_YIELD_SEARCH_TERMS = _triage._LOW_YIELD_SEARCH_TERMS
_matches_accepted_location = _triage._matches_accepted_location
_extract_subscores_dict = _triage._extract_subscores_dict
_normalize_gates_dict = _triage._normalize_gates_dict
_apply_seniority_ceiling = _triage._apply_seniority_ceiling
_apply_deterministic_gates = _triage._apply_deterministic_gates
_clean_short_bullets = _triage._clean_short_bullets
_finalize_triage_result = _triage._finalize_triage_result
_render_quick_eval_md = _triage._render_quick_eval_md
triar_vaga_rapida = _triage.triar_vaga_rapida
_parse_strict_score = _triage._parse_strict_score
_normalize_recruiter_classification = _triage._normalize_recruiter_classification
triar_post_recrutador = _triage.triar_post_recrutador
_sanitize_search_keywords = _triage._sanitize_search_keywords
_pair_key = _triage._pair_key
_fallback_cv_keywords = _triage._fallback_cv_keywords
sortear_palavras_chave_busca = _triage.sortear_palavras_chave_busca
