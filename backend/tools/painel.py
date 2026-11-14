#!/usr/bin/env python3
"""Camada de compatibilidade e persistência JSON/CSV do painel local Vagamundo.

Mantém as funções puras de leitura/gravação em `seen_jobs.json`, `evolucao.json`,
`job_search_tracker.csv`, cache de respostas em `documents/applications/_painel/`
e listagem de documentos gerados consumidas pela API FastAPI e serviços de `backend/core/`.
"""

import csv
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import painel_ia  # noqa: E402
import painel_perfil  # noqa: E402
import scrape_run  # noqa: E402

logger = logging.getLogger(__name__)
ROOT = scrape_run.ROOT

DECISIONS = {
    "interesse": {"fit": "medium", "status": "new"},
    "descartar": {"fit": "low", "status": "skipped"},
}

CLAUDE_DIR = ROOT / "documents" / "applications" / "_painel"
EVOLUTION_PATH = ROOT / "documents" / "evolucao.json"
WORK_CONTEXT_DIR = ROOT.parent / "work"

# O resultado da candidatura é sempre escolhido manualmente no painel. O backend
# valida a chave para que o histórico não acumule variações livres do mesmo status.
APPLICATION_STATUSES = {
    "drafted": "Rascunho",
    "applied": "Enviada",
    "interview": "Entrevista",
    "offer": "Proposta",
    "hired": "Contratação",
    "rejected": "Não seguiu",
    "no_response": "Sem resposta",
    "offer_declined": "Proposta recusada",
    "withdrawn": "Desisti",
}
# passo -> (sufixo do arquivo da resposta,)
CLAUDE_STEPS = {
    "avaliar": ("avaliacao",),
    "curriculo": ("curriculo",),
    "carta": ("carta",),
    "redigir": ("rascunho",),
    "entrevista": ("entrevista",),
    "perfil": ("perfil",),
}
PERFIL_KEY = "perfil"  # o perfil não é de uma vaga: a resposta fica sob esta chave


# ---------------------------------------------------------------------------
# Dados (funções puras, testadas sem servidor)
# ---------------------------------------------------------------------------

def results_path(day: str | None = None) -> Path:
    """O arquivo da busca do painel: na pasta temporária, nunca no repositório."""
    return Path(tempfile.gettempdir()) / f"painel_busca_{day or date.today().isoformat()}.json"


def load_results(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None



def _evolution_default() -> dict:
    """Estrutura inicial do caderno de evolução, sem dados de candidatura."""
    return {
        "version": 1,
        "updated_at": None,
        "applications": {},
        "strengths": [],
        "gaps": [],
        "actions": [],
        "projects": [],
        "evolution": {
            "summary": "Ainda não há uma atualização da evolução.",
            "metrics": {},
            "priorities": [],
        },
        "validation": {
            "checked_at": None,
            "errors": [],
            "warnings": [],
            "sources": {},
        },
    }


def load_evolution(path: Path = EVOLUTION_PATH) -> dict:
    """Lê o JSON local de evolução e cria a estrutura se ela ainda não existir."""
    data = _evolution_default()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass
    if not isinstance(data.get("applications"), dict):
        data["applications"] = {}
    return data


def save_evolution(data: dict, path: Path = EVOLUTION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clean_field(value, limit: int = 20000) -> str:
    return str(value or "").strip()[:limit]


def _tracker_has_url(url: str, tracker_path: Path) -> bool:
    return any((row.get("source") or row.get("url") or "").strip() == url.strip()
               for row in applications(tracker_path))


def _update_tracker_application(url: str, app: dict, tracker_path: Path = scrape_run.TRACKER) -> None:
    """Mantém o CSV legado sincronizado com os campos principais do JSON."""
    if not tracker_path.exists():
        return
    with tracker_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or painel_ia.TRACKER_FIELDS)
        rows = [dict(row) for row in reader]
    details = app.get("job") or {}
    values = app.get("application") or {}
    changed = False
    for row in rows:
        if (row.get("source") or row.get("url") or "").strip() != url.strip():
            continue
        row.update({
            "date": values.get("applied_date") or row.get("date") or date.today().isoformat(),
            "company": details.get("company") or row.get("company") or "",
            "role": details.get("title") or row.get("role") or "",
            "channel": details.get("portal") or row.get("channel") or "",
            "status": values.get("status") or "applied",
            "notes": values.get("notes") or row.get("notes") or "",
            "cv_file": values.get("cv_file") or row.get("cv_file") or "",
            "cover_letter_file": values.get("cover_letter_file") or row.get("cover_letter_file") or "",
            "deadline": details.get("deadline") or row.get("deadline") or "",
        })
        changed = True
    if changed:
        with tracker_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore", restval="")
            writer.writeheader()
            writer.writerows(rows)


def save_application_record(payload: dict, evolution_path: Path = EVOLUTION_PATH,
                            tracker_path: Path = scrape_run.TRACKER,
                            seen_path: Path = scrape_run.SEEN) -> dict:
    """Valida e grava candidatura, detalhes da vaga e novos registros de histórico."""
    if not isinstance(payload, dict):
        raise ValueError("o cadastro da candidatura precisa ser um objeto")
    url = _clean_field(payload.get("url"), 2000)
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError("a vaga precisa ter um endereço http ou https")
    status = _clean_field(payload.get("status"), 40) or "applied"
    if status not in APPLICATION_STATUSES:
        raise ValueError("resultado da candidatura inválido")

    details = {
        "title": _clean_field(payload.get("title") or payload.get("role"), 300),
        "company": _clean_field(payload.get("company"), 300),
        "url": url,
        "portal": _clean_field(payload.get("portal"), 100),
        "date": _clean_field(payload.get("date"), 40),
        "posted_date": _clean_field(payload.get("posted_date"), 40),
        "deadline": _clean_field(payload.get("deadline"), 40),
        "location": _clean_field(payload.get("location"), 300),
        "workplace_type": _clean_field(payload.get("workplace_type"), 80),
        "contract": _clean_field(payload.get("contract"), 120),
        "seniority": _clean_field(payload.get("seniority"), 120),
        "salary": _clean_field(payload.get("salary"), 200),
        "description": _clean_field(payload.get("description"), 30000),
        "skills": payload.get("skills") if isinstance(payload.get("skills"), list) else [],
    }
    values = {
        "applied_date": _clean_field(payload.get("applied_date"), 40) or date.today().isoformat(),
        "status": status,
        "cv_file": _clean_field(payload.get("cv_file"), 500),
        "cover_letter_file": _clean_field(payload.get("cover_letter_file"), 500),
        "notes": _clean_field(payload.get("notes"), 10000),
    }
    if not details["company"] or not details["title"]:
        raise ValueError("empresa e cargo são obrigatórios")
    if not values["cv_file"]:
        raise ValueError("informe o currículo enviado para a vaga")
    try:
        date.fromisoformat(values["applied_date"])
    except ValueError as exc:
        raise ValueError("a data da candidatura deve estar no formato AAAA-MM-DD") from exc

    data = load_evolution(evolution_path)
    current = data["applications"].get(url) or {}
    if not current and not _tracker_has_url(url, tracker_path):
        record_applied(url, details["company"], details["title"], details["portal"], tracker_path, seen_path)
    previous_details = current.get("job") if isinstance(current.get("job"), dict) else {}
    previous_values = current.get("application") if isinstance(current.get("application"), dict) else {}
    merged_details = {**previous_details, **{k: v for k, v in details.items() if v not in ("", [], None)}}
    merged_values = {**previous_values, **values}
    history = current.get("history") if isinstance(current.get("history"), list) else []
    event = {
        "date": _clean_field(payload.get("event_date"), 40),
        "stage": _clean_field(payload.get("event_stage"), 120),
        "feedback": _clean_field(payload.get("event_feedback"), 12000),
        "questions_and_answers": _clean_field(
            payload.get("event_questions_and_answers")
            or payload.get("event_questions")
            or payload.get("event_answers"), 16000
        ),
    }
    if any(event.values()):
        if not event["date"]:
            event["date"] = date.today().isoformat()
        history.append(event)
    record = {
        "url": url,
        "job": merged_details,
        "application": merged_values,
        "history": history,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["applications"][url] = record
    save_evolution(data, evolution_path)
    _update_tracker_application(url, record, tracker_path)
    return record


def _source_info(path: Path) -> dict:
    info = {"path": str(path), "exists": path.exists(), "readable": path.exists(), "files": 0, "lines": 0}
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        info["files"] = len(files)
        return info
    if path.is_file():
        try:
            content = path.read_text(encoding="utf-8")
            info["lines"] = len(content.splitlines())
            info["bytes"] = path.stat().st_size
        except (OSError, UnicodeError):
            info["readable"] = False
    return info


def _projects_from_source(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    collecting = False
    projects = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## Fila de enriquecimento") or line.startswith("## Competências técnicas"):
            collecting = False
            continue
        if (
            line.startswith("## Inventário atual de projetos")
            or line.startswith("## Projetos locais")
            or line.startswith("## Projetos independentes")
            or line.startswith("## Experiência profissional")
        ):
            collecting = True
            continue
        if collecting:
            if line.startswith("### "):
                title = line[4:].strip()
                if title and title not in projects and title != "Modelo de registro" and not title.startswith("Pessoa Jur"):
                    projects.append(title)
            elif line.startswith("- **") and "**:" in line:
                title = line[4:].split("**:")[0].strip()
                if title and title not in projects:
                    projects.append(title)
    return projects


def _profile_skills_summary(path: Path) -> tuple[list[str], list[str], list[str]]:
    strengths, gaps, actions = [], [], []
    if not path.is_file():
        return strengths, gaps, actions
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return strengths, gaps, actions
    in_skills = False
    for line in lines:
        if line.startswith("## Competências técnicas"):
            in_skills = True
            continue
        if in_skills and line.startswith("## "):
            in_skills = False
            break
        if in_skills and line.startswith("- **") and "**" in line[4:]:
            skill = line[4:].split("**")[0].strip()
            detail = line[4:].split("**")[1].lstrip(":").strip()
            if skill:
                strengths.append(f"{skill}: {detail}" if detail else skill)
    return strengths, gaps, actions


def _markdown_section(path: Path, heading: str) -> list[str]:
    """Lê uma seção Markdown sem interpretar blocos de código como dados."""
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    out, active, in_fence = [], False, False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("## "):
            if active:
                break
            active = line.strip() == heading
            continue
        if active and not in_fence:
            out.append(line)
    return out


def _unique_text(items: list[str]) -> list[str]:
    out = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _context_summary(path: Path) -> tuple[list[str], list[str], list[str]]:
    strengths_section = _markdown_section(path, "## Feedback mais recente")
    strengths, gaps, actions = [], [], []
    subsection = None
    in_fence = False
    for line in strengths_section:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("### "):
            subsection = line[4:].strip().lower()
            continue
        if line.startswith("- ") and subsection == "pontos fortes observados":
            strengths.append(line[2:].strip())
        if line.startswith("- ") and subsection == "oportunidades de melhoria":
            gaps.append(line[2:].strip())

    tracking = _markdown_section(path, "## Tracking de lacunas de evidência")
    for line in tracking:
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and cells[0] and cells[0] != "Competência a demonstrar":
            gaps.append(cells[0])

    training = _markdown_section(path, "## Plano de treino")
    for line in training:
        if line.startswith("- [ ] "):
            actions.append(line[6:].strip())
    return _unique_text(strengths), _unique_text(gaps), _unique_text(actions)


def update_evolution(evolution_path: Path = EVOLUTION_PATH,
                     tracker_path: Path = scrape_run.TRACKER,
                     seen_path: Path = scrape_run.SEEN,
                     documents_path: Path = painel_ia.DOCUMENTS,
                     db_path: str | Path | None = None) -> dict:
    """Valida fontes e candidaturas e grava o resultado derivado no JSON."""
    data = load_evolution(evolution_path)
    applications_data = data.setdefault("applications", {})
    warnings, errors = [], []
    for list_name in ("strengths", "gaps", "actions", "projects"):
        if not isinstance(data.get(list_name), list):
            errors.append(f"A seção {list_name} do JSON de evolução precisa ser uma lista.")
            data[list_name] = []

    # 1. Sync from SQLite if available
    repo = None
    try:
        from backend.db.repository import Repository
        repo = Repository(db_path)
        sqlite_apps = repo.list_applications()
        sqlite_events = repo.list_application_events()
        events_by_app_id: dict[int, list[dict]] = {}
        for ev in sqlite_events:
            events_by_app_id.setdefault(ev["application_id"], []).append(ev)

        for sapp in sqlite_apps:
            s_url = (sapp.get("job_url") or sapp.get("url") or "").strip()
            if not s_url:
                continue
            app_id = sapp.get("id")
            app_events = events_by_app_id.get(app_id, [])

            if s_url not in applications_data:
                applications_data[s_url] = {
                    "url": s_url,
                    "job": {
                        "title": sapp.get("job_title") or sapp.get("role") or "",
                        "company": sapp.get("job_company") or sapp.get("company") or "",
                        "portal": sapp.get("job_portal") or sapp.get("portal") or "",
                        "url": s_url,
                    },
                    "application": {
                        "applied_date": sapp.get("applied_date") or "",
                        "status": sapp.get("status") if sapp.get("status") in APPLICATION_STATUSES else "applied",
                        "cv_file": sapp.get("cv_path") or sapp.get("cv_file") or "",
                        "cover_letter_file": sapp.get("cover_letter_path") or sapp.get("cover_letter_file") or "",
                        "notes": sapp.get("notes") or "",
                    },
                    "history": [],
                    "updated_at": sapp.get("updated_at"),
                    "imported_from_tracker": True,
                }
            else:
                existing_entry = applications_data[s_url]
                app_obj = existing_entry.setdefault("application", {})
                if sapp.get("cv_path") and not app_obj.get("cv_file"):
                    app_obj["cv_file"] = sapp["cv_path"]
                if sapp.get("status") and sapp["status"] in APPLICATION_STATUSES:
                    app_obj["status"] = sapp["status"]

            if app_events:
                hist_entries = []
                for ev in app_events:
                    hist_entries.append({
                        "date": ev.get("event_date") or "",
                        "stage": ev.get("stage") or "",
                        "feedback": ev.get("feedback") or "",
                        "questions_and_answers": ev.get("questions_and_answers") or "",
                    })
                applications_data[s_url]["history"] = hist_entries
    except (ImportError, OSError, sqlite3.Error, ValueError, TypeError) as exc:
        logger.warning("Failed to sync applications from SQLite during evolution load: %s", exc)
    finally:
        if repo is not None:
            repo.close()

    # 2. Sync from tracker CSV
    for row in applications(tracker_path):
        url = (row.get("source") or row.get("url") or "").strip()
        if not url:
            warnings.append("Há uma linha no histórico sem URL da vaga.")
            continue
        if url not in applications_data:
            applications_data[url] = {
                "url": url,
                "job": {"title": row.get("role") or "", "company": row.get("company") or "", "portal": row.get("channel") or "", "url": url},
                "application": {"applied_date": row.get("date") or "", "status": row.get("status") if row.get("status") in APPLICATION_STATUSES else "applied", "cv_file": row.get("cv_file") or "", "cover_letter_file": row.get("cover_letter_file") or "", "notes": row.get("notes") or ""},
                "history": [],
                "updated_at": None,
                "imported_from_tracker": True,
            }

    with_feedback = with_questions = with_cv = 0
    for url, item in applications_data.items():
        if not isinstance(item, dict):
            errors.append(f"Cadastro inválido para a vaga {url}.")
            continue
        job = item.get("job") if isinstance(item.get("job"), dict) else {}
        app = item.get("application") if isinstance(item.get("application"), dict) else {}
        if not re.match(r"^https?://", str(url), re.IGNORECASE):
            errors.append(f"URL inválida no cadastro: {url}.")
        if app.get("status") not in APPLICATION_STATUSES:
            errors.append(f"Resultado inválido para {job.get('title') or url}.")
        if app.get("cv_file"):
            with_cv += 1
        else:
            warnings.append(f"Currículo enviado não informado: {job.get('title') or url}.")
        history = item.get("history") if isinstance(item.get("history"), list) else []
        if not isinstance(item.get("history"), list):
            errors.append(f"Histórico inválido para {job.get('title') or url}.")
        for event in history:
            if not isinstance(event, dict):
                errors.append(f"Há um registro de histórico inválido para {job.get('title') or url}.")
                continue
            for event_key in ("date", "stage", "feedback", "questions_and_answers", "questions", "answers"):
                if event_key in event and not isinstance(event[event_key], str):
                    errors.append(f"Campo {event_key} inválido no histórico de {job.get('title') or url}.")
        if any((event.get("feedback") or "").strip() for event in history if isinstance(event, dict)):
            with_feedback += 1
        if any((event.get("questions_and_answers") or event.get("questions") or event.get("answers") or "").strip()
               for event in history if isinstance(event, dict)):
            with_questions += 1

    context_file = WORK_CONTEXT_DIR / "contexto-entrevistas.md"
    projects_file = WORK_CONTEXT_DIR / "fontes.md"
    application_notes_file = WORK_CONTEXT_DIR / "vagas.md"

    profile_src = painel_ia.PROFILE_MD
    if not (
        profile_src.is_file()
        and painel_perfil.is_customized_md(profile_src.read_text(encoding="utf-8"))
    ):
        local_prof = painel_perfil.local_profile_path()
        cached_prof = claude_file(PERFIL_KEY, "perfil")
        if local_prof.is_file():
            profile_src = local_prof
        elif cached_prof.is_file():
            profile_src = cached_prof

    if not projects_file.is_file() and profile_src.is_file():
        projects_file = profile_src

    source_strengths, source_gaps, source_actions = _context_summary(context_file)
    if not source_strengths and profile_src.is_file():
        p_str, p_gap, p_act = _profile_skills_summary(profile_src)
        source_strengths = p_str
        if not source_gaps:
            source_gaps = p_gap
        if not source_actions:
            source_actions = p_act

    if source_strengths:
        data["strengths"] = source_strengths
    if source_gaps:
        data["gaps"] = source_gaps
    if source_actions:
        data["actions"] = source_actions

    # Audited sources (workspace local primary, legacy fallback)
    agents_file = painel_ia.REPO_ROOT / "AGENTS.md" if (painel_ia.REPO_ROOT / "AGENTS.md").is_file() else WORK_CONTEXT_DIR / "AGENTS.md"
    usage_file = painel_ia.REPO_ROOT / "CLAUDE.md" if (painel_ia.REPO_ROOT / "CLAUDE.md").is_file() else WORK_CONTEXT_DIR / "usage.md"
    interviews_src = context_file if context_file.is_file() else (documents_path / "interview" if (documents_path / "interview").exists() else profile_src)
    notes_src = application_notes_file if application_notes_file.is_file() else (documents_path / "applications")

    sources = {
        "applications_tracker": _source_info(tracker_path),
        "candidate_profile": _source_info(profile_src),
        "linkedin": _source_info(documents_path / "linkedin"),
        "projects": _source_info(projects_file),
        "interviews": _source_info(interviews_src),
        "application_notes": _source_info(notes_src),
        "guidance": _source_info(agents_file),
        "usage": _source_info(usage_file),
    }

    if not sources["linkedin"]["exists"] or not sources["linkedin"].get("files"):
        warnings.append("Nenhum arquivo do LinkedIn foi encontrado em backend/documents/linkedin.")
    if not sources["projects"]["exists"]:
        warnings.append("O inventário de projetos não foi encontrado.")

    project_count = 0
    source_projects = _projects_from_source(projects_file)
    if projects_file.is_file():
        try:
            project_count = len(source_projects)
        except (OSError, UnicodeError):
            pass
    if source_projects:
        data["projects"] = source_projects

    if application_notes_file.is_file():
        work_application_section = []
        for line in _markdown_section(application_notes_file, "## Registro de candidaturas"):
            if line.startswith("### "):
                break
            work_application_section.append(line)
        work_application_rows = [line for line in work_application_section
                                 if line.startswith("|") and not line.startswith("|---")
                                 and "Empresa" not in line and "---" not in line]
        if work_application_rows and len(work_application_rows) != len(applications_data):
            warnings.append(
                f"O histórico de candidaturas registra {len(work_application_rows)} candidatura(s), "
                f"mas o rastreador local contém {len(applications_data)}."
            )

    metrics = {
        "applications": len(applications_data),
        "applications_with_cv": with_cv,
        "applications_with_feedback": with_feedback,
        "applications_with_questions": with_questions,
        "projects_in_source": project_count,
        "linkedin_files": sources["linkedin"].get("files", 0),
        "validation_errors": len(errors),
        "validation_warnings": len(warnings),
    }
    priorities = []
    if metrics["applications"] and with_cv < metrics["applications"]:
        priorities.append("Completar o currículo enviado nas candidaturas importadas ou novas.")
    if metrics["applications"] and with_feedback < metrics["applications"]:
        priorities.append("Registrar feedbacks recebidos nas candidaturas.")
    if metrics["applications"] and with_questions < metrics["applications"]:
        priorities.append("Registrar perguntas e respostas das entrevistas.")
    if not metrics["linkedin_files"]:
        priorities.append("Adicionar o LinkedIn salvo em PDF para validar a fonte profissional.")
    if not project_count:
        priorities.append("Adicionar ou confirmar o inventário de projetos.")

    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    data["validation"] = {"checked_at": data["updated_at"], "errors": errors, "warnings": warnings, "sources": sources}
    data["evolution"] = {
        "summary": f"{metrics['applications']} candidatura(s), {project_count} projeto(s) na fonte e {len(priorities)} prioridade(s) de evolução.",
        "metrics": metrics,
        "priorities": priorities,
    }
    save_evolution(data, evolution_path)
    return data


def unseen(results: dict | None, seen_path: Path = scrape_run.SEEN, tracker_path: Path = scrape_run.TRACKER) -> dict:
    """O arquivo da busca sem as vagas que já foram marcadas (aqui ou no /scrape) depois dela."""
    if not results:
        return {"meta": None, "new": []}
    index = scrape_run.load_seen(seen_path, tracker_path)
    rows = [r for r in results.get("new", []) if isinstance(r, dict)
            and not index.match(r.get("company"), r.get("title"), r.get("url"))]
    return {**results, "new": rows}


def mark(results: dict | None, urls: list, decision: str, seen_path: Path = scrape_run.SEEN,
         job_data: dict | None = None) -> dict:
    """Grava a decisão das vagas escolhidas, achadas pela URL no arquivo da busca.

    Quando a vaga é externa (ex: EURES ou Google Careers), job_data pode ser fornecido
    para cadastrar os metadados da vaga caso ela não esteja em results.
    """
    if decision not in DECISIONS:
        raise ValueError(f"decisão desconhecida: {decision}")
    by_url = {r.get("url"): r for r in (results or {}).get("new", []) if isinstance(r, dict) and r.get("url")}
    if job_data and isinstance(job_data, dict) and job_data.get("url"):
        by_url[job_data["url"]] = job_data
    rows, missing = [], []
    for url in urls:
        row = by_url.get(url)
        if row is None:
            missing.append(url)
            continue
        try:
            painel_ia.save_job_cache(url, row)
        except Exception:
            pass
        marked = {
            "title": row.get("title"),
            "company": row.get("company"),
            "url": row.get("url"),
            "date": row.get("date") or row.get("posted_date"),
            "posted_date": row.get("posted_date") or row.get("date"),
            "deadline": row.get("deadline"),
            "portal": row.get("portal"),
            "location": row.get("location"),
            "workplace_type": row.get("workplace_type") or row.get("work_model"),
            "contract": row.get("contract") or row.get("contract_type"),
            "seniority": row.get("seniority"),
            "salary": row.get("salary"),
            "description": row.get("description"),
            "screening": row.get("screening"),
            "source": "painel",
            **DECISIONS[decision],
        }
        if row.get("visa_sponsorship") is True:
            marked["visa_sponsorship"] = True
        rows.append(marked)
    out = scrape_run.record(rows, seen_path)
    out["missing"] = missing
    return out


def record_applied(url: str, company: str, role: str, portal: str = "",
                   tracker_path: Path = scrape_run.TRACKER, seen_path: Path = scrape_run.SEEN) -> dict:
    """Registra a candidatura no tracker.csv e atualiza o status para 'applied' no seen_jobs.json."""
    today_iso = date.today().isoformat()
    # 1. Atualiza seen_jobs.json para que a vaga saia imediatamente de "Me interessam"
    try:
        state = {"version": 1, "updated": today_iso, "seen": {}}
        if seen_path.exists():
            state = json.loads(seen_path.read_text(encoding="utf-8"))
        seen = state.setdefault("seen", {})
        target = None
        key = scrape_run.make_key(company, role, url)
        if key in seen:
            target = seen[key]
        else:
            for k, v in seen.items():
                if isinstance(v, dict) and v.get("url") == url:
                    target = v
                    break
        if target is not None:
            target["status"] = "applied"
            target["applied_date"] = today_iso
            target["source"] = target.get("source") or "painel"
            if company and not target.get("company"):
                target["company"] = company
            if role and not target.get("title"):
                target["title"] = role
        else:
            seen[key] = {
                "title": role, "company": company, "url": url, "portal": portal or "painel",
                "source": "painel", "status": "applied", "fit": "medium", "applied_date": today_iso,
                "first_seen": today_iso,
            }
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to update seen_jobs cache during record_applied: %s", exc)

    # 2. Registra ou atualiza no tracker.csv
    header = list(painel_ia.TRACKER_FIELDS)
    existing = []
    if tracker_path.exists():
        try:
            with tracker_path.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                if reader.fieldnames:
                    header = list(reader.fieldnames)
                existing = [dict(r) for r in reader]
        except Exception:
            pass

    updated_existing = False
    for r in existing:
        if (r.get("source") or "") == url:
            r["status"] = "applied"
            r["date"] = r.get("date") or today_iso
            if company and not r.get("company"):
                r["company"] = company
            if role and not r.get("role"):
                r["role"] = role
            if portal and not r.get("channel"):
                r["channel"] = portal
            updated_existing = True

    if updated_existing:
        try:
            with tracker_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore", restval="")
                writer.writeheader()
                writer.writerows(existing)
        except Exception:
            pass
    else:
        row = {
            "date": today_iso,
            "company": company,
            "role": role,
            "channel": portal or "portal",
            "status": "applied",
            "notes": "Registrado pelo painel",
            "source": url,
        }
        new_file = not tracker_path.exists() or tracker_path.stat().st_size == 0
        try:
            tracker_path.parent.mkdir(parents=True, exist_ok=True)
            with tracker_path.open("a", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore", restval="")
                if new_file:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            pass

    return {"applied": True, "company": company, "role": role, "url": url}


def _stored_row(entry: dict, fields: tuple[str, ...]) -> dict:
    row = {key: entry.get(key) for key in fields}
    if entry.get("visa_sponsorship") is True:
        row["visa_sponsorship"] = True
    return row


def saved(seen_path: Path = scrape_run.SEEN) -> list:
    """As vagas marcadas como "me interessa" no painel, mais recentes primeiro."""
    try:
        state = json.loads(seen_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    fields = (
        "title", "company", "url", "first_seen", "posted_date", "date", "deadline",
        "portal", "status", "location", "workplace_type", "work_model",
        "contract", "contract_type", "seniority", "salary", "description", "screening",
    )
    rows = [
        _stored_row(e, fields)
        for e in state.get("seen", {}).values()
        if isinstance(e, dict) and e.get("source") == "painel"
        and e.get("fit") != "low" and e.get("status") not in ("applied", "skipped")
    ]
    return sorted(rows, key=lambda r: r.get("first_seen") or "", reverse=True)


def discarded(seen_path: Path = scrape_run.SEEN) -> list:
    """As vagas descartadas pelo painel ou pela triagem automática, mais recentes primeiro."""
    try:
        state = json.loads(seen_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    fields = (
        "title", "company", "url", "first_seen", "posted_date", "date", "deadline",
        "portal", "status", "location", "workplace_type", "work_model",
        "contract", "contract_type", "seniority", "salary", "description", "screening", "fit",
    )
    rows = [
        _stored_row(e, fields)
        for e in state.get("seen", {}).values()
        if isinstance(e, dict) and e.get("source") == "painel"
        and (e.get("status") == "skipped" or e.get("fit") == "low")
    ]
    return sorted(rows, key=lambda r: r.get("first_seen") or "", reverse=True)


def remove_application(url: str, to_status: str = "skipped", company: str = "", role: str = "",
                       tracker_path: Path = scrape_run.TRACKER, seen_path: Path = scrape_run.SEEN) -> dict:
    """Remove uma vaga da lista de candidaturas no tracker.csv e atualiza seen_jobs.json."""
    clean_url = (url or "").strip()
    if tracker_path.exists():
        try:
            with tracker_path.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                fieldnames = list(reader.fieldnames or painel_ia.TRACKER_FIELDS)
                rows = []
                for r in reader:
                    r_source = (r.get("source") or "").strip()
                    if clean_url and r_source == clean_url:
                        continue
                    if company and role and (r.get("company") or "").strip() == company.strip() and (r.get("role") or "").strip() == role.strip():
                        continue
                    rows.append(r)
            with tracker_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore", restval="")
                writer.writeheader()
                writer.writerows(rows)
        except Exception:
            pass

    if seen_path.exists():
        try:
            state = json.loads(seen_path.read_text(encoding="utf-8"))
            seen = state.get("seen", {})
            for k, v in seen.items():
                if isinstance(v, dict):
                    v_url = (v.get("url") or "").strip()
                    if clean_url and v_url == clean_url:
                        v["status"] = to_status
                        v["fit"] = "low"
                    elif company and role and (v.get("company") or "").strip() == company.strip() and (v.get("title") or "").strip() == role.strip():
                        v["status"] = to_status
                        v["fit"] = "low"
            seen_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return {"removed": True, "url": url}


def _set_seen_url_state(
    url: str,
    *,
    result_key: str,
    fit: str,
    status: str,
    seen_path: Path,
) -> dict:
    if not seen_path.exists():
        return {result_key: False, "url": url}
    try:
        state = json.loads(seen_path.read_text(encoding="utf-8"))
        seen = state.get("seen", {})
        found = False
        for v in seen.values():
            if isinstance(v, dict) and v.get("url") == url:
                v["fit"] = fit
                v["status"] = status
                v["source"] = "painel"
                found = True
        if found:
            seen_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return {result_key: found, "url": url}
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to update seen_jobs state for %s (%s): %s", url, result_key, exc)
        return {result_key: False, "url": url}


def restore_job(url: str, seen_path: Path = scrape_run.SEEN) -> dict:
    """Restaura uma vaga descartada para 'Me interessam'."""
    return _set_seen_url_state(
        url,
        result_key="restored",
        fit="medium",
        status="new",
        seen_path=seen_path,
    )


def discard_job(url: str, seen_path: Path = scrape_run.SEEN) -> dict:
    """Move uma vaga de 'Me interessam' para 'Descartadas'."""
    return _set_seen_url_state(
        url,
        result_key="discarded",
        fit="low",
        status="skipped",
        seen_path=seen_path,
    )


def unmark_interested(url: str, seen_path: Path = scrape_run.SEEN) -> bool:
    """Remove do seen_jobs.json uma vaga revertida pelo desfazer do Modo Automático."""
    if not url or not seen_path.exists():
        return False
    try:
        state = json.loads(seen_path.read_text(encoding="utf-8"))
        seen = state.get("seen", {})
        keys_to_del = [
            k for k, v in seen.items()
            if isinstance(v, dict) and (v.get("url") or "").strip() == url.strip()
        ]
        if not keys_to_del:
            return False
        for k in keys_to_del:
            del seen[k]
        seen_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


def job_pdfs(company: str, role: str) -> dict:
    """Localiza os PDFs de currículo, carta e dossiê de entrevista para uma empresa/cargo."""
    company_slug = painel_ia.sanitize_filename(company or "")
    role_slug = painel_ia.sanitize_filename(role or "")
    out = {"pdf_cv": None, "pdf_carta": None, "pdf_entrevista": None}
    if not company_slug or company_slug == "documento":
        return out

    def _find_best(folder: Path, prefix: str, exts: tuple[str, ...] = (".pdf",)) -> str | None:
        if not folder.exists():
            return None
        for ext in exts:
            if role_slug and role_slug != "documento":
                exact = sorted(folder.glob(f"{prefix}_{company_slug}_*{role_slug[:20]}*{ext}"),
                               key=lambda p: p.stat().st_mtime, reverse=True)
                if exact:
                    return str(exact[0].relative_to(ROOT)).replace("\\", "/")
            matches = sorted(folder.glob(f"{prefix}_*{company_slug}*{ext}"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            if matches:
                return str(matches[0].relative_to(ROOT)).replace("\\", "/")
        return None

    out["pdf_cv"] = _find_best(ROOT / "cv", "main", (".pdf",))
    out["pdf_carta"] = _find_best(ROOT / "cover_letters", "cover", (".pdf",))
    out["pdf_entrevista"] = _find_best(ROOT / "documents" / "interview", "prep", (".pdf", ".md"))
    return out


def delete_generated_document(rel_path: str) -> dict:
    """Exclui somente um currículo gerado e os arquivos derivados do mesmo nome."""
    rel = str(rel_path or "").replace("\\", "/").strip("/")
    cv_root = (ROOT / "cv").resolve()
    target = (ROOT / rel).resolve()
    if (target.parent != cv_root or target.suffix.lower() != ".pdf"
            or not target.name.startswith("main_") or target.name == "main_example.pdf"):
        raise ValueError("só é permitido excluir currículos PDF gerados")
    if not target.is_file():
        return {"deleted": False, "path": rel, "removed": []}

    removed = []
    for suffix in (".pdf", ".tex", ".aux", ".log", ".out", ".fls", ".fdb_latexmk", ".synctex.gz"):
        candidate = cv_root / f"{target.stem}{suffix}"
        if candidate.is_file() and candidate.parent == cv_root:
            candidate.unlink()
            removed.append(str(candidate.relative_to(ROOT)).replace("\\", "/"))
    return {"deleted": True, "path": rel, "removed": removed}


def list_generated_documents() -> list:
    """Lista todos os PDFs gerados (currículos, cartas e dossiês de entrevista)."""
    known_jobs = []
    try:
        if scrape_run.SEEN.exists():
            st = json.loads(scrape_run.SEEN.read_text(encoding="utf-8"))
            for v in st.get("seen", {}).values():
                if isinstance(v, dict) and v.get("company"):
                    known_jobs.append({
                        "company": v.get("company") or "",
                        "role": v.get("title") or "",
                        "url": v.get("url") or "",
                        "company_slug": painel_ia.sanitize_filename(v.get("company") or ""),
                        "role_slug": painel_ia.sanitize_filename(v.get("title") or ""),
                    })
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to read seen_jobs cache while listing jobs for documents: %s", exc)
    for app in applications():
        if app.get("company"):
            known_jobs.append({
                "company": app.get("company") or "",
                "role": app.get("role") or "",
                "url": app.get("source") or "",
                "company_slug": painel_ia.sanitize_filename(app.get("company") or ""),
                "role_slug": painel_ia.sanitize_filename(app.get("role") or ""),
            })

    items = []
    sources = [
        ("cv", "Currículo", ROOT / "cv", "main_*.pdf"),
        ("carta", "Carta de Apresentação", ROOT / "cover_letters", "cover_*.pdf"),
        ("entrevista", "Dossiê de Entrevista", ROOT / "documents" / "interview", "prep_*.pdf"),
    ]
    for kind, label, folder, pattern in sources:
        if not folder.exists():
            continue
        for pdf in folder.glob(pattern):
            if not pdf.is_file():
                continue
            stat = pdf.stat()
            stem = pdf.stem
            matched_company = ""
            matched_role = ""
            matched_url = ""
            for kj in known_jobs:
                c_slug = kj["company_slug"]
                if c_slug and c_slug != "documento" and c_slug in stem:
                    matched_company = kj["company"]
                    matched_role = kj["role"]
                    matched_url = kj["url"]
                    if kj["role_slug"] and kj["role_slug"][:15] in stem:
                        break
            comp = job_pdfs(matched_company, matched_role)
            letter_text = ""
            if matched_url:
                h = hashlib.sha256(matched_url.encode("utf-8")).hexdigest()[:16]
                tf = CLAUDE_DIR / f"{h}_carta_texto.txt"
                if tf.exists():
                    try:
                        letter_text = tf.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass
            if not letter_text and comp.get("pdf_carta"):
                tex_file = (ROOT / comp["pdf_carta"]).with_suffix(".tex")
                if tex_file.exists():
                    try:
                        letter_text = painel_ia._extract_plain_letter("", tex_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass
            elif not letter_text and kind == "carta":
                tex_file = pdf.with_suffix(".tex")
                if tex_file.exists():
                    try:
                        letter_text = painel_ia._extract_plain_letter("", tex_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass

            items.append({
                "kind": kind,
                "label": label,
                "name": pdf.name,
                "path": str(pdf.relative_to(ROOT)).replace("\\", "/"),
                "mtime": stat.st_mtime,
                "date": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "size_kb": max(1, round(stat.st_size / 1024)),
                "company": matched_company,
                "role": matched_role,
                "url": matched_url,
                "letter_text": letter_text,
                "pdf_cv": comp.get("pdf_cv"),
                "pdf_carta": comp.get("pdf_carta"),
                "pdf_entrevista": comp.get("pdf_entrevista"),
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def claude_file(url: str, step: str, base: Path = CLAUDE_DIR) -> Path:
    """Onde fica a resposta do Claude para uma vaga: o nome vem de um hash da URL, nunca do texto dela."""
    suffix = CLAUDE_STEPS[step][0]
    return base / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}_{suffix}.md"


def claude_answer(url: str, step: str, base: Path = CLAUDE_DIR) -> str | None:
    try:
        return claude_file(url, step, base).read_text(encoding="utf-8")
    except OSError:
        return None


def claude_answers(url: str, base: Path = CLAUDE_DIR) -> dict:
    return {step: claude_answer(url, step, base) for step in ("avaliar", "curriculo", "carta", "redigir", "entrevista")}


def applications(tracker_path: Path = scrape_run.TRACKER) -> list:
    if not tracker_path.exists():
        return []
    with tracker_path.open(encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def priorities(queries_path: Path | None = None) -> list:
    """As prioridades com linhas de busca prontas (as do modelo, com [YOUR_...], não contam)."""
    queries_path = scrape_run.active_queries_path(queries_path)
    try:
        calls = scrape_run.parse_queries(queries_path.read_text(encoding="utf-8"))
    except OSError:
        return []
    count = {}
    for prio, portal, _ in calls:
        count.setdefault(prio, set()).add(portal)
    return [{"priority": p, "queries": sum(1 for c in calls if c[0] == p), "portals": len(count[p])} for p in sorted(count)]

def get_cached_score(url: str, batch_results: dict | None = None) -> dict | None:
    if batch_results and url in batch_results and batch_results[url].get("score") is not None:
        return batch_results[url]
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    eval_f = CLAUDE_DIR / f"{h}_avaliacao.md"
    if eval_f.exists():
        try:
            content = eval_f.read_text(encoding="utf-8")
            m_score = re.search(r"Nota\s*(?:geral)?\s*[:=]?\s*\**\s*(\d+)\s*(?:/\s*100)?", content, re.IGNORECASE)
            m_verdict = re.search(r"(?:Veredito|Encaixe)\s*[:=]?\s*\**\s*([^\n*]+)", content, re.IGNORECASE)
            m_model = re.search(r"Modelo(?:\s+IA)?\s*[:=]\s*[*`]*\s*([^\n*`]+)", content, re.IGNORECASE)
            summary = ""
            m_sum = re.search(r"##+\s*Resumo[^\n]*\n+(.+?)(?:\n\n|\n-\s*URL:|$)", content, re.IGNORECASE | re.DOTALL)
            if not m_sum:
                m_sum = re.search(r"##+\s*Recomenda[çc][ãa]o[^\n]*\n+(.+?)(?:\n\n|\n##|$)", content, re.IGNORECASE | re.DOTALL)
            if m_sum:
                summary = m_sum.group(1).strip()

            if m_score:
                details = painel_ia.extract_eval_details_from_md(content)
                result = {
                    "score": int(m_score.group(1)),
                    "verdict": m_verdict.group(1).strip(" *[]") if m_verdict else "Concluído",
                    "summary": summary,
                    "ai_model": m_model.group(1).strip(" *`") if m_model else None,
                }
                for key in ("subscores", "location_verdict", "language_gate", "language_note", "strengths", "gaps", "guard_alert"):
                    if details.get(key):
                        result[key] = details[key]
                return result
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to parse cached score for %s: %s", url, exc)
    return None


def enriched_applications(tracker_path: Path = scrape_run.TRACKER, seen_path: Path = scrape_run.SEEN,
                          claude_base: Path = CLAUDE_DIR, batch_results: dict | None = None,
                          evolution_path: Path = EVOLUTION_PATH) -> list:
    """Enriquece as candidaturas do tracker.csv (e seen_jobs.json) com avaliação, PDFs e notas."""
    raw_rows = applications(tracker_path)
    evolution_data = load_evolution(evolution_path)
    evolution_apps = evolution_data.get("applications", {})
    seen_by_url = {}
    try:
        if seen_path.exists():
            st = json.loads(seen_path.read_text(encoding="utf-8"))
            for v in st.get("seen", {}).values():
                if isinstance(v, dict) and v.get("url"):
                    seen_by_url[v["url"]] = v
                    if v.get("status") == "applied" and not any((r.get("source") or "") == v["url"] for r in raw_rows):
                        raw_rows.append({
                            "date": v.get("applied_date") or v.get("first_seen") or "",
                            "company": v.get("company") or "",
                            "role": v.get("title") or "",
                            "channel": v.get("portal") or "painel",
                            "status": "applied",
                            "notes": "Registrado pelo painel",
                            "source": v["url"],
                        })
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to read seen_jobs cache during application enrichment: %s", exc)

    out = []
    seen_urls = set()
    for r in reversed(raw_rows):
        url = (r.get("source") or r.get("url") or "").strip()
        if r.get("status") == "drafted" and seen_by_url.get(url, {}).get("status") != "applied":
            continue
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        s_info = seen_by_url.get(url, {})
        company = r.get("company") or s_info.get("company") or ""
        role = r.get("role") or r.get("title") or s_info.get("title") or ""
        portal = r.get("channel") or r.get("portal") or s_info.get("portal") or ""
        pdfs = job_pdfs(company, role)
        answers = claude_answers(url, claude_base) if url else {}
        screening = get_cached_score(url, batch_results) if url else None
        item = {
            **r,
            "url": url,
            "title": role,
            "role": role,
            "company": company,
            "portal": portal,
            "first_seen": r.get("date") or s_info.get("first_seen") or "",
            "claude": answers,
            "screening": screening,
            **pdfs,
        }
        evolution_record = evolution_apps.get(url) if isinstance(evolution_apps, dict) else None
        if isinstance(evolution_record, dict):
            item["evolution"] = evolution_record
            evo_app = evolution_record.get("application") if isinstance(evolution_record.get("application"), dict) else {}
            item["status"] = evo_app.get("status") or item.get("status") or "applied"
            item["cv_file"] = evo_app.get("cv_file") or item.get("cv_file") or ""
            item["cover_letter_file"] = evo_app.get("cover_letter_file") or item.get("cover_letter_file") or ""
            item["history"] = evolution_record.get("history") or []
        if s_info.get("visa_sponsorship") is True:
            item["visa_sponsorship"] = True
        out.append(item)
    out.sort(key=lambda item: (
        item.get("date") or "",
        (item.get("screening") or {}).get("score", -1) if isinstance(item.get("screening"), dict) else -1,
    ), reverse=True)
    return out
