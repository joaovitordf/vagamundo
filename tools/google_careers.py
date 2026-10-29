"""Busca e análise de vagas públicas no Google Careers (careers.google.com).

Acessa a rota pública de resultados (jobs/results), extrai a descrição completa
(Minimum qualifications, Preferred qualifications, Responsibilities, About) e já
calcula nota, veredito, resumo analítico e alertas de elegibilidade.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

try:
    import posting_signals
except ImportError:
    posting_signals = None

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    txt = re.sub(r"<li[^>]*>", "\n- ", raw, flags=re.I)
    txt = re.sub(r"<br\s*/?>|</p>|</div>|</h3>|</ul>", "\n", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html_lib.unescape(txt)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in txt.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _fetch_page_items(query: str, location: str, page: int = 1, target_level: str | None = None) -> list[dict]:
    params = [f"q={urllib.parse.quote(query)}", f"page={page}"]
    if location:
        params.append(f"location={urllib.parse.quote(location)}")
    if target_level:
        params.append(f"target_level={urllib.parse.quote(target_level)}")

    url = f"https://www.google.com/about/careers/applications/jobs/results?{'&'.join(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            page_html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    m = re.search(
        r"AF_initDataCallback\(\{key:\s*'ds:1'.*?data:(.*?)(?:,\s*sideChannel:|\s*\}\);)",
        page_html,
        re.DOTALL,
    )
    if not m:
        return []

    try:
        data, _ = json.JSONDecoder().raw_decode(m.group(1).strip())
        if data and isinstance(data, list) and len(data) > 0:
            return data[0] or []
    except Exception:
        pass
    return []


def evaluate_google_job(
    title: str,
    location: str,
    min_qual: str,
    pref_qual: str,
    responsibilities: str,
    about: str,
    notes: str,
) -> tuple[dict, list[str]]:
    """Analisa a descrição completa da vaga do Google e retorna (screening, warnings)."""
    t_low = title.lower()
    loc_low = location.lower()
    min_low = min_qual.lower()
    full_low = f"{title}\n{min_qual}\n{pref_qual}\n{responsibilities}\n{about}\n{notes}".lower()

    warnings: list[str] = []

    # 1. Filtros de elegibilidade (vagas afirmativas exclusivas / cidadania restrita / fora do Brasil)
    is_women_exclusive = "for women in tech" in t_low or "for women in tech" in notes.lower()
    is_pcd_exclusive = "people with disabilities" in t_low
    is_foreign_citizenship = "mexican citizenship" in full_low or "us citizenship" in full_low
    in_brazil = any(k in loc_low for k in ("brazil", "brasil", "belo horizonte", "são paulo", "sao paulo", "minas gerais"))

    if is_women_exclusive:
        warnings.append("vaga exclusiva afirmativa (Women in Tech)")
    if is_pcd_exclusive:
        warnings.append("vaga exclusiva afirmativa (PcD / People with Disabilities)")
    if is_foreign_citizenship:
        warnings.append("exige cidadania estrangeira específica")
    if not in_brazil and "remote" not in loc_low:
        warnings.append(f"presencial/híbrido fora do Brasil ({location})")

    # Extrai anos de experiência exigidos nas qualificações mínimas
    years_matches = [int(y) for y in re.findall(r"(\d+)\+?\s*years?\s+of\s+experience", min_low)]
    min_years = max(years_matches) if years_matches else 0

    # Detecta senioridade fora da faixa (Sênior, Staff, Tech Lead, Manager)
    is_manager = any(k in t_low for k in ("manager", "director", "head of", "lead, americas"))
    is_staff_lead = any(k in t_low for k in ("staff ", "principal ", "tech lead"))
    is_senior = "senior " in t_low or "sr." in t_low or " iii" in t_low or min_years >= 5

    if is_manager:
        warnings.append(f"cargo de gestão/gerência ({min_years or 7}+ anos exigidos)")
    elif is_staff_lead:
        warnings.append(f"senioridade fora da faixa (Staff/Lead - {min_years or 8}+ anos)")
    elif is_senior:
        warnings.append(f"senioridade fora da faixa (Sênior - {min_years}+ anos nas qualificações mínimas)")

    # Detecta tecnologias e domínios citados na descrição
    matched_techs = []
    for label, kw in [
        ("Python", "python"),
        ("Java", "java"),
        ("JavaScript/TypeScript", "javascript"),
        ("C/C++ (transferível)", "c++"),
        ("SQL/Bancos de Dados", "sql"),
        ("AI/ML", "machine learning"),
        ("GenAI/LLMs", "generative ai"),
        ("Full Stack", "full stack"),
        ("Cloud", "cloud"),
        ("Estruturas de Dados e Algoritmos", "data structures"),
    ]:
        if kw in full_low:
            matched_techs.append(label)
    tech_str = ", ".join(matched_techs[:4]) if matched_techs else "fundamentos de Ciência da Computação"

    # Caso 1: Fora do Brasil sem remoto elegível ou cidadania estrangeira
    if not in_brazil or is_foreign_citizenship:
        return (
            {
                "score": 15,
                "verdict": "Poor Fit",
                "summary": (
                    f"Vaga localizada fora das praças elegíveis ({location}) ou com restrição de cidadania/autorização local. "
                    f"As qualificações mínimas pedem {min_years or 3}+ anos de experiência."
                ),
            },
            warnings,
        )

    # Caso 2: Vagas exclusivas afirmativas (Women in Tech / PcD)
    if is_women_exclusive or is_pcd_exclusive:
        grupo = "mulheres (Women in Tech)" if is_women_exclusive else "pessoas com deficiência (PcD)"
        exp_info = f"{min_years} ano(s) de experiência" if min_years else "graduação em Computação"
        return (
            {
                "score": 20,
                "verdict": "Poor Fit",
                "summary": (
                    f"Tecnicamente alinhada ({tech_str}, pede {exp_info} em {location}), "
                    f"porém o anúncio é de ação afirmativa exclusiva para {grupo}."
                ),
            },
            warnings,
        )

    # Caso 3: Áreas não técnicas (Jurídico, RH, Finanças, Vendas puras)
    non_tech = any(
        k in t_low
        for k in (
            "litigation counsel",
            "employee relations",
            "finance analyst",
            "field sales",
            "sales specialist",
            "sales representative",
            "account manager, people",
            "energy initiatives",
            "commercials and incentives",
            "performance specialist",
        )
    )
    if non_tech:
        return (
            {
                "score": 22,
                "verdict": "Poor Fit",
                "summary": (
                    f"Vaga fora de engenharia de software/computação ({title}) e que exige {min_years or 4}+ anos "
                    "de experiência corporativa específica na área comercial, jurídica ou financeira."
                ),
            },
            warnings,
        )

    # Caso 4: Cargos de Gerência / Staff / Tech Lead (8+ anos)
    if is_manager or is_staff_lead or min_years >= 7:
        return (
            {
                "score": 38,
                "verdict": "Weak Fit",
                "summary": (
                    f"Casa na formação em Ciência da Computação, localidade ({location}) e stack ({tech_str}). "
                    f"Teto aplicado pois as qualificações mínimas exigem {min_years or 8}+ anos de experiência e liderança sênior."
                ),
            },
            warnings,
        )

    # Caso 5: Cargos Sênior / Pleno-Sênior (5 a 6 anos exigidos no Minimum Qualifications)
    if is_senior or min_years >= 5:
        return (
            {
                "score": 45,
                "verdict": "Weak Fit",
                "summary": (
                    f"Excelente aderência temática e geográfica ({location}) com {tech_str} e Bacharelado em Ciência da Computação. "
                    f"Nota limitada ao teto de senioridade pois a descrição exige {min_years} anos de experiência mínima."
                ),
            },
            warnings,
        )

    # Caso 6: Cargos Júnior / Early Career / Pleno (0 a 4 anos exigidos)
    is_swe_or_ai = any(k in t_low for k in ("software engineer", "early career", "ai", "developer", "data scientist"))
    if min_years <= 2 and is_swe_or_ai:
        score = 88
        verdict = "Strong Fit"
        summary = (
            f"Encaixe direto: pede Bacharelado em Ciência da Computação e {min_years or 1} ano de experiência em desenvolvimento "
            f"({tech_str}) em {location}, alinhado ao seu perfil e tempo de experiência."
        )
    elif min_years <= 3:
        score = 74
        verdict = "Good Fit"
        summary = (
            f"Boa compatibilidade com o Bacharelado em Ciência da Computação e base em {tech_str} ({location}). "
            f"As qualificações mínimas pedem {min_years} anos de experiência técnica ou resolução de problemas."
        )
    else:
        score = 64
        verdict = "Moderate Fit"
        summary = (
            f"Alinhada à formação em Computação e tecnologias ({tech_str}) em {location}. "
            f"Principal ponto de atenção é o requisito de {min_years} anos de experiência nas qualificações mínimas."
        )

    return ({"score": score, "verdict": verdict, "summary": summary}, warnings)


def fetch_google_careers(
    queries: list[str] | None = None,
    locations: list[str] | None = None,
    max_pages: int = 1,
    target_level: str | None = None,
    max_workers: int = 5,
) -> list[dict]:
    """Busca vagas no Google Careers (Brasil), analisa a descrição completa e retorna lista pontuada."""
    if queries is None:
        queries = [
            "Software Engineer",
            "Computer Science",
            "Early Career",
            "Developer",
            "AI",
            "Cloud",
            "Technical Solutions",
            "Data",
        ]
    if locations is None:
        locations = ["Brazil", "Belo Horizonte", "São Paulo"]

    tasks = []
    for loc in locations:
        for q in queries:
            for p in range(1, max_pages + 1):
                tasks.append((q, loc, p))

    seen_ids: set[str] = set()
    raw_items = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_fetch_page_items, q, loc, p, target_level)
            for (q, loc, p) in tasks
        ]
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    raw_items.extend(res)
            except Exception:
                pass

    jobs_out: list[dict] = []
    for item in raw_items:
        if not item or len(item) < 2:
            continue
        job_id = str(item[0])
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        title = str(item[1] or "(Sem título)")

        # Localidade
        loc_str = ""
        if len(item) > 9 and item[9] and isinstance(item[9], list):
            loc_item = item[9][0]
            if isinstance(loc_item, list) and len(loc_item) > 0:
                loc_str = str(loc_item[0] or "")

        # Ignora vagas que o Google retornou fora do Brasil sem modalidade remota
        loc_lower = loc_str.lower()
        if not any(k in loc_lower for k in ("brazil", "brasil", "belo horizonte", "são paulo", "sao paulo", "remote")):
            continue

        # Ignora áreas puramente jurídicas, RH, contábeis ou vendas não técnicas
        t_lower = title.lower()
        if any(
            k in t_lower
            for k in (
                "litigation counsel",
                "employee relations",
                "finance analyst",
                "field sales representative",
                "energy initiatives",
                "commercials and incentives",
                "performance specialist",
            )
        ):
            continue

        company = "Google"
        if len(item) > 7 and item[7]:
            company = str(item[7])

        job_date = None
        if len(item) > 12 and item[12] and isinstance(item[12], list):
            try:
                epoch = int(item[12][0])
                if epoch > 1e11:
                    epoch = epoch // 1000
                job_date = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                pass
        if not job_date:
            job_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if "remote" in loc_lower or "remoto" in loc_lower:
            workplace = "remote"
        else:
            workplace = "hybrid"

        job_url = f"https://www.google.com/about/careers/applications/jobs/results/{job_id}"

        # Extração completa da descrição da vaga (About, Minimum/Preferred Qualifications, Responsibilities, Notes)
        about_html = str(item[10][1] or "") if (len(item) > 10 and item[10] and len(item[10]) > 1) else ""
        min_q_html = str(item[4][1] or "") if (len(item) > 4 and item[4] and len(item[4]) > 1) else ""
        pref_q_html = str(item[19][1] or "") if (len(item) > 19 and item[19] and len(item[19]) > 1) else ""
        resp_html = str(item[3][1] or "") if (len(item) > 3 and item[3] and len(item[3]) > 1) else ""
        notes_html = str(item[15][1] or "") if (len(item) > 15 and item[15] and len(item[15]) > 1) else ""

        about_txt = _strip_html(about_html)
        min_q_txt = _strip_html(min_q_html)
        pref_q_txt = _strip_html(pref_q_html)
        resp_txt = _strip_html(resp_html)
        notes_txt = _strip_html(notes_html)

        sections = []
        if min_q_txt:
            sections.append(f"Minimum Qualifications:\n{min_q_txt}")
        if pref_q_txt:
            sections.append(f"Preferred Qualifications:\n{pref_q_txt}")
        if resp_txt:
            sections.append(f"Responsibilities:\n{resp_txt}")
        if about_txt:
            sections.append(f"About the job:\n{about_txt}")
        if notes_txt:
            sections.append(f"Additional Notes:\n{notes_txt}")
        full_desc = "\n\n".join(sections)

        screening, warn_list = evaluate_google_job(
            title=title,
            location=loc_str,
            min_qual=min_q_txt,
            pref_qual=pref_q_txt,
            responsibilities=resp_txt,
            about=about_txt,
            notes=notes_txt,
        )

        signals: dict = {}
        if posting_signals:
            try:
                signals = posting_signals.analyse(
                    f"{title}\n{loc_str}\n{full_desc}",
                    title=title,
                    accept={"junior", "pleno", "especialista"},
                )
            except Exception:
                signals = {}

        if warn_list:
            signals["verdict"] = "posting_signals: " + "; ".join(warn_list)
        elif posting_signals and signals:
            signals["verdict"] = posting_signals.verdict(signals)
        else:
            signals["verdict"] = "posting_signals: none"

        jobs_out.append({
            "id": job_id,
            "title": title,
            "company": company,
            "location": loc_str or "Brasil",
            "date": job_date,
            "url": job_url,
            "portal": "google-careers",
            "workplace_type": workplace,
            "description": full_desc,
            "signals": signals,
            "screening": screening,
        })

    # Ordena pelas maiores notas primeiro
    jobs_out.sort(key=lambda r: (r.get("screening") or {}).get("score", 0), reverse=True)
    return jobs_out


if __name__ == "__main__":
    jobs = fetch_google_careers(max_pages=1)
    print(f"Total Google Brasil: {len(jobs)}")
    for j in jobs[:10]:
        sc = j["screening"]
        w = j["signals"].get("verdict")
        print(f"[{sc['score']}/100 - {sc['verdict']}] {j['title']} ({j['location']})")
        print(f"   Resumo: {sc['summary']}")
        if w and w != "posting_signals: none":
            print(f"   Aviso: {w}")
