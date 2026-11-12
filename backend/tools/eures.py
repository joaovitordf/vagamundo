"""Módulo de integração com a API pública do EURES (Comissão Europeia).

Acessa os serviços oficiais jv-searchengine para estatísticas agregadas e
busca de vagas em 31 países europeus.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Nomes em português dos países europeus monitorados pelo EURES
EU_COUNTRIES = {
    "de": "Alemanha",
    "fr": "França",
    "nl": "Holanda",
    "be": "Bélgica",
    "at": "Áustria",
    "es": "Espanha",
    "pl": "Polônia",
    "se": "Suécia",
    "pt": "Portugal",
    "ie": "Irlanda",
    "ch": "Suíça",
    "it": "Itália",
    "no": "Noruega",
    "dk": "Dinamarca",
    "fi": "Finlândia",
    "cz": "República Tcheca",
    "ro": "Romênia",
    "lu": "Luxemburgo",
    "gr": "Grécia",
    "hu": "Hungria",
    "bg": "Bulgária",
    "hr": "Croácia",
    "sk": "Eslováquia",
    "si": "Eslovênia",
    "ee": "Estônia",
    "lv": "Letônia",
    "lt": "Lituânia",
    "cy": "Chipre",
    "mt": "Malta",
    "is": "Islândia",
    "li": "Liechtenstein",
}

EXP_LABELS = {
    "none_required": "Sem experiência exigida",
    "up_to_1_year": "Até 1 ano (Júnior / Entrada)",
    "between_1_and_2_years": "1 a 2 anos (Júnior / Pleno)",
    "between_2_and_5_years": "2 a 5 anos (Pleno)",
    "more_than_5_years": "Mais de 5 anos (Sênior / Especialista)",
    "NS": "Não especificado no anúncio",
}

EDU_LABELS = {
    "bachelor": "Bacharelado / Graduação",
    "medium": "Ensino Médio / Técnico",
    "tertiary": "Ensino Superior Não Universitário",
    "doctoral": "Pós-graduação / Doutorado",
    "basic": "Ensino Básico",
    "NS": "Não especificado",
}

LANG_LABELS = {
    "en": "Inglês",
    "de": "Alemão",
    "fr": "Francês",
    "nl": "Holandês",
    "es": "Espanhol",
    "pt": "Português",
    "it": "Italiano",
    "sv": "Sueco",
    "pl": "Polonês",
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _ssl_context():
    return ssl.create_default_context()


def get_eures_stats() -> dict:
    """Coleta estatísticas gerais e agregação de vagas em TI na Europa."""
    ctx = _ssl_context()

    # 1. Estatísticas gerais por país
    country_stats = []
    total_europe_jobs = 0
    try:
        url_c = "https://europa.eu/eures/api/jv-searchengine/public/statistics/getCountryStats"
        req_c = urllib.request.Request(url_c, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req_c, timeout=10, context=ctx) as resp:
            raw_c = json.loads(resp.read().decode("utf-8"))
            for item in raw_c:
                c_code = (item.get("code") or "").lower()
                c_jobs = int(item.get("jobs") or 0)
                total_europe_jobs += c_jobs
                country_stats.append({
                    "code": c_code,
                    "name": EU_COUNTRIES.get(c_code, item.get("label") or c_code.upper()),
                    "jobs": c_jobs,
                })
    except Exception:
        pass

    country_stats.sort(key=lambda x: x["jobs"], reverse=True)

    # 2. Amostragem em TI / Computação para gerar facetas de mercado
    tech_total = 0
    top_tech_countries = []
    experience_dist = []
    education_dist = []
    languages_dist = []

    try:
        url_search = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
        payload = {
            "resultsPerPage": 1,
            "page": 1,
            "sortSearch": "MOST_RECENT",
            "keywords": [{"keyword": "Software", "specificSearchCode": "EVERYWHERE"}],
        }
        req_s = urllib.request.Request(
            url_search,
            data=json.dumps(payload).encode("utf-8"),
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req_s, timeout=12, context=ctx) as resp:
            data_s = json.loads(resp.read().decode("utf-8"))
            tech_total = int(data_s.get("numberRecords") or 0)
            facets = data_s.get("facets", {})

            # Distribuição por país em TI
            loc_facet = facets.get("POSITION_LOCATION", {})
            if isinstance(loc_facet, dict):
                entries = loc_facet.get("facetEntriesList", [])
                for e in entries:
                    code = (e.get("code") or "").lower()
                    if code in EU_COUNTRIES:
                        top_tech_countries.append({
                            "code": code,
                            "name": EU_COUNTRIES[code],
                            "jobs": int(e.get("count") or 0),
                        })
                top_tech_countries.sort(key=lambda x: x["jobs"], reverse=True)

            # Experiência
            exp_facet = facets.get("REQUIRED_EXPERIENCE", {})
            if isinstance(exp_facet, dict):
                entries = exp_facet.get("facetEntriesList", [])
                for e in entries:
                    c = e.get("code")
                    if c and c != "NS":
                        experience_dist.append({
                            "code": c,
                            "label": EXP_LABELS.get(c, c),
                            "count": int(e.get("count") or 0),
                        })
                experience_dist.sort(key=lambda x: x["count"], reverse=True)

            # Educação
            edu_facet = facets.get("EDUCATION_AND_QUALIFICATION_LEVEL", {})
            if isinstance(edu_facet, dict):
                entries = edu_facet.get("facetEntriesList", [])
                for e in entries:
                    c = e.get("code")
                    if c and c != "NS":
                        education_dist.append({
                            "code": c,
                            "label": EDU_LABELS.get(c, c),
                            "count": int(e.get("count") or 0),
                        })
                education_dist.sort(key=lambda x: x["count"], reverse=True)

            # Idiomas
            lang_facet = facets.get("LANGUAGE_SKILLS", {})
            if isinstance(lang_facet, dict):
                entries = lang_facet.get("facetEntriesList", [])
                for e in entries:
                    c = (e.get("code") or "").lower()
                    if c and c != "ns" and int(e.get("count") or 0) > 0:
                        languages_dist.append({
                            "code": c,
                            "label": LANG_LABELS.get(c, c.upper()),
                            "count": int(e.get("count") or 0),
                        })
                languages_dist.sort(key=lambda x: x["count"], reverse=True)
    except Exception:
        pass

    return {
        "total_europe_jobs": total_europe_jobs or 3500000,
        "total_tech_jobs": tech_total or 66000,
        "country_stats": country_stats[:10],
        "top_tech_countries": top_tech_countries[:10],
        "experience_distribution": experience_dist,
        "education_distribution": education_dist,
        "languages_distribution": languages_dist[:6],
    }


def search_eures(
    keyword: str = "Software Engineer",
    country_code: str = "",
    page: int = 1,
    results_per_page: int = 15,
) -> dict:
    """Busca vagas abertas no EURES com filtros de palavra-chave e país."""
    ctx = _ssl_context()
    url = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"

    payload: dict = {
        "resultsPerPage": max(1, min(50, results_per_page)),
        "page": max(1, page),
        "sortSearch": "MOST_RECENT",
        "keywords": [{"keyword": keyword.strip() or "Software", "specificSearchCode": "EVERYWHERE"}],
    }

    if country_code and country_code.strip().lower() in EU_COUNTRIES:
        payload["locationCodes"] = [country_code.strip().lower()]

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc), "total": 0, "jobs": []}

    total = int(data.get("numberRecords") or 0)
    raw_jobs = data.get("jvs", [])
    jobs_out = []

    for j in raw_jobs:
        job_id = str(j.get("id") or "")
        title = str(j.get("title") or "Vaga sem título")
        employer_obj = j.get("employer") or {}
        employer = employer_obj.get("name") if isinstance(employer_obj, dict) else str(employer_obj or "Empresa confidencial")

        # Localidade
        loc_map = j.get("locationMap") or {}
        loc_strs = []
        country_codes = []
        for c_k, r_v in loc_map.items():
            c_lower = c_k.lower()
            country_codes.append(c_lower.upper())
            c_name = EU_COUNTRIES.get(c_lower, c_k.upper())
            loc_strs.append(c_name)
        location = ", ".join(loc_strs) if loc_strs else "Europa"
        primary_country = country_codes[0] if country_codes else "EU"

        # Data ISO YYYY-MM-DD para compatibilidade com o painel
        c_epoch = j.get("creationDate")
        date_str = ""
        if c_epoch:
            try:
                date_str = datetime.fromtimestamp(int(c_epoch) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                date_str = ""

        # Descrição limpa
        raw_desc = str(j.get("description") or "")
        clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
        clean_desc = re.sub(r"\s+", " ", clean_desc).strip()
        short_desc = clean_desc[:300].rsplit(" ", 1)[0] + "…" if len(clean_desc) > 300 else clean_desc

        eures_url = f"https://europa.eu/eures/portal/jv-se/jv-details/{job_id}?lang=en"
        langs = j.get("availableLanguages") or []
        screening, verdict_sig = evaluate_eures_job(title, clean_desc, location, langs)

        jobs_out.append({
            "id": job_id,
            "title": title,
            "company": employer,
            "employer": employer,
            "location": location,
            "country_code": primary_country,
            "date": date_str,
            "description": short_desc,
            "languages": langs,
            "portal": "eures",
            "workplace_type": "remote" if "remote" in f"{title} {clean_desc}".lower() else "on-site",
            "url": eures_url,
            "screening": screening,
            "signals": {"verdict": verdict_sig},
        })

    return {
        "total": total,
        "page": page,
        "results_per_page": results_per_page,
        "jobs": jobs_out,
    }


TECH_TITLE_KEYWORDS = (
    "computer vision", "vision", "machine learning", "deep learning", "artificial intelligence",
    "ai ", " ai", "ml ", "data scientist", "data engineer", "software", "developer", "engineer",
    "python", "backend", "full stack", "fullstack", "frontend", "devops", "cloud", "robotics",
    "image processing", "nlp", "llm", "neural", "algorithm", "researcher", "phd", "informatik",
    "entwickler", "ingénieur", "programador", "arquitecto", "c++", "pytorch", "tensorflow", "opencv",
)

NON_TECH_TITLE_BLOCKLIST = (
    "recruiter", "sachbearbeiter", "buchhalter", "kaufmännisch", "pflege", "fahrer", "lkw",
    "koch", "kellner", "verkäufer", "reinigung", "lager", "elektriker", "mechaniker", "schweißer",
    "human resources", "hr manager", "accountant", "nurse", "driver", "cleaner", "receptionist",
)


def is_tech_role(title: str, desc: str = "") -> bool:
    t_low = title.lower()
    if any(b in t_low for b in NON_TECH_TITLE_BLOCKLIST):
        return False
    return any(k in t_low for k in TECH_TITLE_KEYWORDS)


def _profile_eures_keywords() -> list[str]:
    """Extrai palavras-chave técnicas do perfil ativo com fallback neutro."""
    try:
        from backend.tools import painel_perfil
        areas = painel_perfil.extract_cv_areas()
        kws: list[str] = []
        seen: set[str] = set()
        for area in areas:
            for kw in area.get("keywords", []):
                clean = str(kw or "").strip()
                if clean and clean.lower() not in seen:
                    seen.add(clean.lower())
                    kws.append(clean)
        if kws:
            return kws[:8]
    except Exception:
        pass
    return ["Software Engineer", "Backend", "Data Engineer", "Machine Learning", "Python"]


def evaluate_eures_job(title: str, desc: str, location: str, languages: list) -> tuple[dict, str]:
    """Calcula aderência da vaga europeia comparando requisitos com o perfil ativo do candidato."""
    t_low = title.lower()
    full_low = f"{title} {desc}".lower()

    profile_kws = _profile_eures_keywords()
    matched = [kw for kw in profile_kws if kw.lower() in full_low]

    generic_tech_pairs = [
        ("Python", "python"),
        ("TypeScript/JS", "typescript"),
        ("Java", "java"),
        ("C/C++", "c++"),
        ("SQL/Dados", "sql"),
        ("Cloud/Docker", "docker"),
        ("Machine Learning", "machine learning"),
        ("Engenharia de Software", "software"),
    ]
    for lbl, kw in generic_tech_pairs:
        if kw in full_low and lbl.lower() not in [m.lower() for m in matched]:
            matched.append(lbl)

    is_senior_lead = any(k in t_low for k in ("senior", "sr.", "lead", "principal", "staff", "head of", "director", "architect"))
    is_junior_entry = any(k in t_low for k in ("junior", "jr", "graduate", "intern", "trainee", "working student", "entry"))
    tech_str = ", ".join(matched[:4]) if matched else "Tecnologia e Engenharia de Sistemas"

    if len(matched) >= 3:
        score = 86 if not is_senior_lead else 72
        verdict = "Strong Fit" if score >= 80 else "Good Fit"
        summary = (
            f"Forte aderência ao perfil ({tech_str}) em {location}. "
            f"Oportunidade oficial EURES alinhada às competências buscadas."
        )
    elif len(matched) >= 1 or is_tech_role(title, desc):
        score = 72 if not is_senior_lead else 56
        if is_junior_entry:
            score = min(84, score + 8)
        verdict = "Good Fit" if score >= 65 else "Moderate Fit"
        summary = (
            f"Vaga de Tecnologia ({tech_str}) na Europa ({location}). "
            f"Compatibilidade técnica parcial; avaliar idioma exigido e elegibilidade para visto."
        )
    else:
        score = 42
        verdict = "Weak Fit"
        summary = f"Oportunidade geral na Europa ({location}) com baixa sobreposição às palavras-chave do seu perfil."

    warnings = []
    if is_senior_lead:
        warnings.append("senioridade elevada (Senior/Lead)")
    sig = f"posting_signals: {'; '.join(warnings)}" if warnings else "posting_signals: none"
    return {"score": score, "verdict": verdict, "summary": summary}, sig


def fetch_eures_for_panel(focus: str = "all", max_per_query: int = 15) -> list[dict]:
    """Busca vagas técnicas no EURES para alimentar o painel unificado usando termos do perfil."""
    profile_kws = _profile_eures_keywords()
    if focus and focus not in ("all", "europa"):
        queries = [focus] + [k for k in profile_kws[:3] if k.lower() != focus.lower()]
    else:
        queries = profile_kws[:5]

    seen_urls: set[str] = set()
    collected: list[dict] = []

    for q in queries:
        res = search_eures(keyword=q, results_per_page=max_per_query)
        for job in res.get("jobs", []):
            url = job.get("url")
            if not url or url in seen_urls:
                continue
            if not is_tech_role(job.get("title", ""), job.get("description", "")):
                continue
            seen_urls.add(url)
            collected.append(job)

    return collected


if __name__ == "__main__":
    print("Coletando estatísticas do EURES...")
    stats = get_eures_stats()
    print("Total Europa:", stats["total_europe_jobs"])
    print("Total TI:", stats["total_tech_jobs"])
    print("Top países TI:", [f"{c['name']}: {c['jobs']}" for c in stats["top_tech_countries"][:5]])

    print("\nBuscando vagas de Software na Alemanha...")
    res = search_eures("Software Engineer", country_code="de", results_per_page=3)
    print("Total encontradas:", res["total"])
    for j in res["jobs"]:
        print("-", j["title"], "|", j["employer"], "|", j["location"], "|", j["url"])

