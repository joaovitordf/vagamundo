"""Coleta, higienização, cache e extração de metadados de anúncios de vagas."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ._facade import ai_providers, facade, posting_guard, posting_signals
from .context import _extract_claude_profile_section

_HIGH_SIGNAL_LINE_RE = re.compile(
    r"(?:requisit|qualifica|obrigat|desej|diferenc|experi[êe]nc|senior|j[úu]nior|pleno|idioma|"
    r"ingl[êe]s|english|espanhol|local|cidade|estado|modalidade|remoto|remote|h[íi]brid|hybrid|"
    r"presencial|on-?site|contrata|regime|clt|pj|contractor|eor|visa|visto|cidadania|citizenship|"
    r"exclusiv|afirmativ|intern[oa]|requirements|qualifications|must\s+have|nice\s+to\s+have|"
    r"responsibilities|location|salary|remunera|benef[íi]cio)",
    re.I,
)


def resolve_portal_skill(url: str) -> str | None:
    """Identifica qual skill em .agents/skills/ trata a URL fornecida."""
    hostname = (urlparse(url).hostname or "").lower()
    for host_pattern, skill in facade().PORTAL_HOST_MAP.items():
        if hostname == host_pattern or hostname.endswith("." + host_pattern):
            return skill
    return None


def _run(cmd: list[str], timeout: int, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        cwd=facade().ROOT,
        timeout=timeout,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def _find_cached_job(url: str) -> dict | None:
    """Procura metadados e descrição da vaga no cache local do painel, nos arquivos temporários e no seen_jobs.json."""
    if not url:
        return None
    f = facade()
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    merged: dict = {}

    seen_file = f.ROOT / "job_scraper" / "seen_jobs.json"
    if seen_file.exists():
        try:
            seen_data = json.loads(seen_file.read_text(encoding="utf-8")).get("seen", {})
            for entry in seen_data.values():
                if isinstance(entry, dict) and entry.get("url") == url:
                    merged.update({k: v for k, v in entry.items() if v is not None})
                    break
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            f.logger.warning("Failed to read seen_jobs cache for %s: %s", url, exc) if hasattr(f, "logger") else None

    try:
        tmp_dir = Path(tempfile.gettempdir())
        for cand in sorted(tmp_dir.glob("painel_busca_*.json"), reverse=True):
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                for j in data.get("new", []) + data.get("jobs", []):
                    if isinstance(j, dict) and j.get("url") == url:
                        merged.update({k: v for k, v in j.items() if v is not None})
                        break
                if merged.get("description"):
                    break
            except (OSError, json.JSONDecodeError, TypeError):
                continue
    except OSError:
        pass

    cache_file = f.PAINEL_DIR / f"{h}_vaga.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                for k, v in cached.items():
                    if v is not None and not merged.get(k):
                        merged[k] = v
        except (OSError, json.JSONDecodeError):
            pass

    if merged:
        f.save_job_cache(url, merged)
        return merged
    return None


def save_job_cache(url: str, job_data: dict) -> None:
    """Salva os metadados completos e a descrição da vaga em _painel/{h}_vaga.json para acesso futuro."""
    if not url or not isinstance(job_data, dict):
        return
    try:
        painel_dir = facade().PAINEL_DIR
        painel_dir.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        cache_file = painel_dir / f"{h}_vaga.json"
        existing = {}
        if cache_file.exists():
            try:
                existing = json.loads(cache_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
        merged = {**existing, **{k: v for k, v in job_data.items() if v is not None}}
        cache_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def _load_candidate_triage_rules() -> dict[str, Any]:
    """Lê preferências não sensíveis (senioridade, modelo, locais, regimes, idiomas) de respostas.json / CLAUDE.md."""
    answers: dict[str, Any] = {}
    ans_path = facade().DOCUMENTS / "perfil" / "respostas.json"
    if ans_path.exists():
        try:
            loaded = json.loads(ans_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                answers = loaded
        except (OSError, json.JSONDecodeError):
            answers = {}

    raw_sen = answers.get("senioridade")
    if isinstance(raw_sen, str):
        raw_sen = [raw_sen]
    accept_seniority = [
        str(x).strip().lower()
        for x in (raw_sen or [])
        if str(x).strip().lower() in posting_signals.LEVELS
    ]
    if not accept_seniority:
        claude_sec = _extract_claude_profile_section().lower()
        found = [
            lvl
            for lvl in posting_signals.LEVELS
            if lvl in claude_sec
        ]
        accept_seniority = found or ["junior", "pleno"]

    locais = str(answers.get("locais") or "").strip()
    if not locais:
        for line in _extract_claude_profile_section().splitlines():
            if "localidade" in line.lower() or "presencial" in line.lower():
                locais += " " + line
    regimes = [str(r).strip() for r in (answers.get("regimes") or []) if str(r).strip()]
    modelo = [str(m).strip().lower() for m in (answers.get("modelo") or []) if str(m).strip()]
    idiomas = [str(i).strip() for i in (answers.get("idiomas") or []) if str(i).strip()]
    return {
        "accept_seniority": accept_seniority,
        "locais": locais.strip(),
        "regimes": regimes,
        "modelo": modelo,
        "idiomas": idiomas,
    }


def _apply_posting_guard(raw_text: str) -> tuple[str, dict[str, Any]]:
    """Executa posting_guard em memória para higienizar HTML oculto, unicode invisível e detectar tampering."""
    try:
        cleaned, findings = posting_guard.guard(raw_text or "", "auto")
        return cleaned, findings
    except (ValueError, TypeError, AttributeError):
        return raw_text or "", {"verdict": "posting_guard: clean"}


def _compact_posting_text(text: str, max_chars: int = 7500) -> str:
    """Compacta textos longos preservando cabeçalho, introdução e seções de requisitos/local/idioma."""
    normalized = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if len(normalized) <= max_chars:
        return normalized

    head_budget = max(1200, int(max_chars * 0.48))
    head = normalized[:head_budget].rstrip()
    tail = normalized[head_budget:]

    selected_lines: list[str] = []
    seen_low: set[str] = set()
    used = len(head) + 32
    lines = tail.splitlines()
    for idx, line in enumerate(lines):
        clean_ln = line.strip()
        if not clean_ln:
            continue
        low = clean_ln.lower()
        if low in seen_low:
            continue
        if _HIGH_SIGNAL_LINE_RE.search(clean_ln):
            chunk = clean_ln
            if idx + 1 < len(lines) and lines[idx + 1].strip():
                nxt = lines[idx + 1].strip()
                if nxt.lower() not in seen_low and len(chunk) < 120:
                    chunk = f"{chunk}\n{nxt}"
                    seen_low.add(nxt.lower())
            if used + len(chunk) + 1 > max_chars:
                break
            seen_low.add(low)
            selected_lines.append(chunk)
            used += len(chunk) + 1

    if selected_lines:
        return f"{head}\n\n[... trechos-chave extraídos ...]\n" + "\n".join(selected_lines)
    return normalized[:max_chars]


def _prompt_posting_budget(prompt_prefix_len: int, profile_len: int, hard_cap: int = 7500) -> int:
    """Garante que o prompt completo caiba com folga dentro do limite MAX_ARGV_CHARS (Windows CLI)."""
    safety_margin = 1600
    remaining = ai_providers.MAX_ARGV_CHARS - prompt_prefix_len - profile_len - safety_margin
    return max(2600, min(hard_cap, remaining))


def _format_structured_header(job_data: dict | None) -> str:
    """Gera um cabeçalho estruturado com título, empresa, localidade, modalidade e sinais de senioridade."""
    if not job_data or not isinstance(job_data, dict):
        return ""
    title = job_data.get("title") or job_data.get("role") or ""
    company = job_data.get("company") or ""
    location = job_data.get("location") or "Não informada"
    work_mode = job_data.get("workplace_type") or job_data.get("work_mode") or "Não informado"
    seniority = job_data.get("seniority") or ""
    salary = job_data.get("salary") or ""
    signals = job_data.get("signals")
    sig_verdict = ""
    if isinstance(signals, dict):
        sig_verdict = signals.get("verdict") or ""
        if not seniority and signals.get("seniority"):
            s_list = signals.get("seniority")
            seniority = ", ".join(s_list) if isinstance(s_list, list) else str(s_list)
    elif isinstance(signals, list):
        sig_verdict = ", ".join(str(x) for x in signals)
    skills = job_data.get("skills") or []
    skills_str = ", ".join(skills) if isinstance(skills, list) else str(skills)

    lines = ["### Metadados Estruturados do Anúncio"]
    if title:
        lines.append(f"- **Cargo / Título:** {title}")
    if company:
        lines.append(f"- **Empresa:** {company}")
    lines.append(f"- **Localidade anunciada:** {location}")
    lines.append(f"- **Modelo de trabalho:** {work_mode}")
    if seniority:
        lines.append(f"- **Senioridade detectada:** {seniority}")
    if salary:
        lines.append(f"- **Remuneração informada:** {salary}")
    if skills_str:
        lines.append(f"- **Tecnologias mapeadas:** {skills_str}")
    if sig_verdict and sig_verdict != "posting_signals: none":
        lines.append(f"- **Alerta do analisador estático (posting_signals):** {sig_verdict}")
    return "\n".join(lines) + "\n\n"


def _detect_language(text: str) -> str:
    """Detecta se o texto da vaga está em inglês ('en') ou português ('pt')."""
    t = (text or "").lower()
    en_hits = sum(
        1
        for k in (
            "requirements",
            "responsibilities",
            "we are looking for",
            "experience with",
            "about the role",
            "what you will do",
            "qualifications",
            "must have",
            "years of experience",
        )
        if k in t
    )
    pt_hits = sum(
        1
        for k in (
            "requisitos",
            "responsabilidades",
            "sobre a vaga",
            "benefícios",
            "contratação",
            "desejável",
            "experiência com",
            "atribuições",
            "desejáveis",
        )
        if k in t
    )
    return "en" if en_hits >= 2 and en_hits > pt_hits else "pt"


def fetch_posting(url: str, job_data: dict | None = None) -> dict:
    """Coleta o texto da vaga, injeta cabeçalho estruturado de metadados e passa pelo posting_guard em todos os níveis."""
    f = facade()
    scheme = urlparse(url).scheme
    if scheme not in ("http", "https", "recruiter"):
        raise ValueError("a vaga precisa ter um endereço http ou https")

    if job_data and isinstance(job_data, dict):
        f.save_job_cache(url, job_data)
        cached = f._find_cached_job(url)
        if cached:
            job_data = {**cached, **{k: v for k, v in job_data.items() if v is not None}}
    else:
        job_data = f._find_cached_job(url)

    skill = (job_data or {}).get("portal") or f.resolve_portal_skill(url)
    title_val = (job_data or {}).get("title") or (job_data or {}).get("role") or ""
    company_val = (job_data or {}).get("company") or ""
    posting_raw = None

    if job_data:
        desc = (job_data.get("description") or "").strip()
        if len(desc) > 80 or (scheme == "recruiter" and desc):
            posting_raw = desc

    if not posting_raw and scheme in ("http", "https") and skill:
        cli_path = f.REPO_ROOT / ".agents" / "skills" / skill / "cli" / "src" / "cli.ts"
        if cli_path.exists() and shutil.which("bun"):
            try:
                proc = f._run(["bun", "run", str(cli_path), "detail", url, "--format", "plain"], 30)
                if proc.returncode == 0:
                    posting_raw = proc.stdout.decode("utf-8", errors="replace").strip()
            except (OSError, subprocess.SubprocessError):
                posting_raw = None

    if scheme in ("http", "https") and not posting_raw:
        try:
            proc = f._run([sys.executable, str(f.ROOT / "tools" / "fetch_page.py"), url, "--text"], 45)
            out = proc.stdout.decode("utf-8", errors="replace")
            if "--- text ---" in out:
                posting_raw = out.split("--- text ---", 1)[1].strip()
            elif proc.returncode == 0:
                posting_raw = out.strip()
        except (OSError, subprocess.SubprocessError):
            posting_raw = None

    if not posting_raw:
        if job_data:
            posting_raw = (
                "Nota: A página externa do anúncio bloqueou conexões automatizadas (robots.txt / firewall). "
                "A avaliação baseia-se nos metadados e sinais coletados na indexação da vaga."
            )
        else:
            raise RuntimeError(f"Não foi possível coletar a vaga na URL: {url}")

    clean_body, guard_findings = f._apply_posting_guard(posting_raw)
    guard_verdict = str((guard_findings or {}).get("verdict") or "posting_guard: clean")

    rules = f._load_candidate_triage_rules()
    portal_lvl = (job_data or {}).get("seniority") if isinstance(job_data, dict) else None
    computed_sig = posting_signals.analyse(
        clean_body,
        title=title_val,
        company=company_val,
        accept=rules["accept_seniority"],
        portal_level=portal_lvl,
    )
    computed_sig["verdict"] = posting_signals.verdict(computed_sig)

    enriched_job_data = dict(job_data) if isinstance(job_data, dict) else {}
    existing_sig = enriched_job_data.get("signals")
    if isinstance(existing_sig, dict):
        merged_sig = {**computed_sig, **{k: v for k, v in existing_sig.items() if v is not None}}
        if not merged_sig.get("verdict") or merged_sig["verdict"] == "posting_signals: none":
            merged_sig["verdict"] = posting_signals.verdict(merged_sig)
        enriched_job_data["signals"] = merged_sig
    else:
        enriched_job_data["signals"] = computed_sig

    header = f._format_structured_header(enriched_job_data)
    if "⚠" in guard_verdict:
        guard_line = f"- **Alerta de integridade (posting_guard):** {guard_verdict}\n"
        header = (header + guard_line) if header else f"### Metadados Estruturados do Anúncio\n{guard_line}\n"

    clean = clean_body if clean_body.startswith("### Metadados") else (header + clean_body)
    raw_with_header = posting_raw if posting_raw.startswith("### Metadados") else (header + posting_raw)

    return {
        "text": clean,
        "raw": raw_with_header,
        "portal": skill,
        "title": title_val,
        "company": company_val,
        "job_data": enriched_job_data or job_data,
        "signals": enriched_job_data.get("signals") or computed_sig,
        "guard_verdict": guard_verdict,
        "guard_findings": guard_findings,
    }


def _extract_meta(posting_text: str, extra: str = "") -> dict:
    f = facade()
    prompt = f"""A partir do texto da vaga abaixo, retorne APENAS um objeto JSON no formato:
{{"empresa": "NomeDaEmpresa", "cargo": "NomeDoCargo"{extra}}}
Sem explicações, apenas o JSON.

{f._vaga_block(posting_text[:2000])}
"""
    try:
        with f._json_mode():
            return f._json_object(f.call_llm(prompt, temperature=0.0))
    except (ValueError, RuntimeError, OSError):
        return {}


def _resolve_meta(posting: dict) -> dict:
    """Resolve empresa, cargo e idioma priorizando os metadados já conhecidos da vaga."""
    f = facade()
    text = posting.get("text") or ""
    idioma = f._detect_language(text)
    empresa = (posting.get("company") or "").strip()
    cargo = (posting.get("title") or "").strip()
    if empresa and cargo:
        return {"empresa": empresa, "cargo": cargo, "idioma": idioma}
    extracted = f._extract_meta(text, extra=', "idioma": "pt"')
    if extracted.get("idioma") in ("en", "pt"):
        idioma = extracted["idioma"]
    return {
        "empresa": empresa or str(extracted.get("empresa") or "Empresa"),
        "cargo": cargo or str(extracted.get("cargo") or "Vaga"),
        "idioma": idioma,
    }
