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

import rank_state
import scrape_run

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
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"google_careers: page {page} failed ({query}, {location}): {exc}\n")
    return []


_BRAZIL_CITIES = (
    "brazil", "brasil", ", br", "são paulo", "sao paulo", "belo horizonte",
    "rio de janeiro", "campinas", "curitiba", "porto alegre", "florianópolis",
    "florianopolis", "brasília", "brasilia", "recife", "salvador", "fortaleza",
    "minas gerais",
)


def _is_brazil_location(location: str) -> bool:
    loc_low = (location or "").lower()
    return any(k in loc_low for k in _BRAZIL_CITIES)


def _load_profile_prefs() -> dict:
    """Lê preferências do perfil local sem exigir dependências opcionais."""
    try:
        try:
            from backend.tools import painel_perfil
        except ImportError:
            import painel_perfil
        return painel_perfil.load_answers() or {}
    except (ImportError, OSError, AttributeError, ValueError):
        return {}


def _profile_terms(ans: dict) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for field in ("cargos", "palavras_chave_sorteio"):
        raw = ans.get(field)
        if isinstance(raw, list):
            for item in raw:
                clean = str(item or "").strip()
                if clean and clean.lower() not in seen:
                    seen.add(clean.lower())
                    terms.append(clean)
    return terms


def _default_brazil_locations() -> list[str]:
    locs = ["Brazil"]
    ans = _load_profile_prefs()
    cidade = str(ans.get("cidade") or "").strip()
    city_name = re.split(r"[,/\-]+", cidade)[0].strip()
    if city_name and city_name.lower() not in ("brazil", "brasil") and city_name not in locs:
        locs.append(city_name)
    return locs


def evaluate_google_job(
    title: str,
    location: str,
    min_qual: str,
    pref_qual: str,
    responsibilities: str,
    about: str,
    notes: str,
    accept_sen: set[str] | None = None,
    profile_ans: dict | None = None,
) -> tuple[dict, list[str]]:
    """Analisa a descrição completa da vaga do Google e retorna (screening, warnings)."""
    t_low = title.lower()
    loc_low = location.lower()
    min_low = min_qual.lower()
    full_low = f"{title}\n{min_qual}\n{pref_qual}\n{responsibilities}\n{about}\n{notes}".lower()

    ans = profile_ans if profile_ans is not None else _load_profile_prefs()
    candidate_gender = str(ans.get("genero") or "").strip().lower()
    custom_terms = [t.lower() for t in _profile_terms(ans)]

    warnings: list[str] = []

    # 1. Filtros de elegibilidade (vagas afirmativas exclusivas / cidadania restrita / fora do Brasil)
    is_women_exclusive = "for women in tech" in t_low or "for women in tech" in notes.lower()
    is_pcd_exclusive = "people with disabilities" in t_low
    is_foreign_citizenship = "mexican citizenship" in full_low or "us citizenship" in full_low
    in_brazil = _is_brazil_location(location)

    if is_women_exclusive:
        if candidate_gender == "masculino":
            warnings.append("vaga exclusiva afirmativa (Women in Tech)")
        elif candidate_gender != "feminino":
            warnings.append("vaga afirmativa para mulheres (Women in Tech — confirme elegibilidade)")
    if is_pcd_exclusive:
        warnings.append("vaga exclusiva afirmativa (PcD / People with Disabilities)")
    if is_foreign_citizenship:
        warnings.append("exige cidadania estrangeira específica")
    if not in_brazil and "remote" not in loc_low:
        warnings.append(f"presencial/híbrido fora do Brasil ({location})")

    # Extrai anos de experiência exigidos nas qualificações mínimas
    years_matches = [int(y) for y in re.findall(r"(\d+)\+?\s*years?\s+of\s+experience", min_low)]
    min_years = max(years_matches) if years_matches else (posting_signals.extract_min_years_required(min_qual) or 0 if posting_signals else 0)

    if accept_sen is None:
        accept_sen = set(scrape_run.local_target_seniority() or ["junior", "pleno"])

    # Detecta senioridade fora da faixa (Sênior, Staff, Tech Lead, Manager)
    is_manager = ("gestao" not in accept_sen) and any(k in t_low for k in ("manager", "director", "head of", "lead, americas"))
    is_staff_lead = ("staff" not in accept_sen and "lead" not in accept_sen) and any(k in t_low for k in ("staff ", "principal ", "tech lead"))
    is_senior = ("senior" not in accept_sen) and ("senior " in t_low or "sr." in t_low or " iii" in t_low or min_years >= 5)

    if is_manager:
        warnings.append(f"cargo de gestão/gerência ({min_years or 7}+ anos exigidos)")
    elif is_staff_lead:
        warnings.append(f"senioridade fora da faixa (Staff/Lead - {min_years or 8}+ anos)")
    elif is_senior:
        warnings.append(f"senioridade fora da faixa (Sênior - {min_years}+ anos nas qualificações mínimas)")

    # Detecta competências citadas na descrição (termos do perfil + base geral)
    matched_techs = [term for term in _profile_terms(ans) if term.lower() in full_low]
    seen_labels = {m.lower() for m in matched_techs}
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
        if kw in full_low and label.lower() not in seen_labels:
            matched_techs.append(label)
            seen_labels.add(label.lower())
    tech_str = ", ".join(matched_techs[:4]) if matched_techs else "requisitos gerais da vaga"

    # Caso 1: Fora do Brasil sem remoto elegível ou cidadania estrangeira
    if not in_brazil or is_foreign_citizenship:
        score = 15
        return (
            {
                "score": score,
                "verdict": rank_state.band(score),
                "summary": (
                    f"Vaga localizada fora das praças elegíveis ({location}) ou com restrição de cidadania/autorização local. "
                    f"As qualificações mínimas pedem {min_years or 3}+ anos de experiência."
                ),
            },
            warnings,
        )

    # Caso 2: Vagas exclusivas afirmativas incompatíveis (Women in Tech quando masculino / PcD)
    women_blocked = is_women_exclusive and candidate_gender == "masculino"
    if women_blocked or is_pcd_exclusive:
        score = 25
        grupo = "mulheres (Women in Tech)" if women_blocked else "pessoas com deficiência (PcD)"
        exp_info = f"{min_years} ano(s) de experiência" if min_years else "formação na área"
        return (
            {
                "score": score,
                "verdict": rank_state.band(score),
                "summary": (
                    f"Tecnicamente alinhada ({tech_str}, pede {exp_info} em {location}), "
                    f"porém o anúncio é de ação afirmativa exclusiva para {grupo}."
                ),
            },
            warnings,
        )

    # Caso 3: Áreas não técnicas (só descartadas se não constarem nos interesses do perfil)
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
    matches_profile = any(term in t_low or term in full_low for term in custom_terms)
    if non_tech and not matches_profile:
        score = 22
        return (
            {
                "score": score,
                "verdict": rank_state.band(score),
                "summary": (
                    f"Vaga fora da área principal configurada no perfil ({title}), exigindo {min_years or 4}+ anos "
                    "de atuação específica nessa frente corporativa."
                ),
            },
            warnings,
        )

    # Caso 4: Cargos de Gerência / Staff / Tech Lead (8+ anos)
    if is_manager or is_staff_lead or ("senior" not in accept_sen and min_years >= 7):
        score = 38
        return (
            {
                "score": score,
                "verdict": rank_state.band(score),
                "summary": (
                    f"Alinhada em localidade ({location}) e stack ({tech_str}). "
                    f"Teto aplicado pois as qualificações mínimas exigem {min_years or 8}+ anos de experiência e liderança sênior."
                ),
            },
            warnings,
        )

    # Caso 5: Cargos Sênior / Pleno-Sênior (5 a 6 anos exigidos no Minimum Qualifications)
    if is_senior or ("senior" not in accept_sen and min_years >= 5):
        return (
            {
                "score": 45,
                "verdict": "Weak Fit",
                "summary": (
                    f"Boa aderência temática e geográfica ({location}) com {tech_str}. "
                    f"Nota limitada ao teto de senioridade pois a descrição exige {min_years} anos de experiência mínima."
                ),
            },
            warnings,
        )

    # Caso 6: Cargos Júnior / Early Career / Pleno (0 a 4 anos exigidos)
    is_target_role = any(
        k in t_low
        for k in ("software engineer", "early career", "ai", "developer", "data scientist", *custom_terms)
    )
    if min_years <= 2 and is_target_role:
        score = 88
        summary = (
            f"Encaixe direto: pede {min_years or 1} ano(s) de experiência na área "
            f"({tech_str}) em {location}, alinhado à faixa de senioridade inicial/plena."
        )
    elif min_years <= 3:
        score = 74
        summary = (
            f"Boa compatibilidade com o perfil ({tech_str}) em {location}. "
            f"As qualificações mínimas pedem {min_years} anos de experiência."
        )
    else:
        score = 58
        summary = (
            f"Alinhada às competências ({tech_str}) em {location}. "
            f"Principal ponto de atenção é o requisito de {min_years} anos de experiência nas qualificações mínimas."
        )

    return ({"score": score, "verdict": rank_state.band(score), "summary": summary}, warnings)


def fetch_google_careers(
    queries: list[str] | None = None,
    locations: list[str] | None = None,
    max_pages: int = 1,
    target_level: str | None = None,
    max_workers: int = 5,
) -> list[dict]:
    """Busca vagas no Google Careers (Brasil), analisa a descrição completa e retorna lista pontuada."""
    profile_ans = _load_profile_prefs()
    accept_sen = set(scrape_run.local_target_seniority() or ["junior", "pleno"])
    profile_kws = _profile_terms(profile_ans)

    if queries is None:
        if profile_kws:
            queries = profile_kws[:8]
        else:
            queries = [
                "Software Engineer",
                "Project Manager",
                "Data Analyst",
                "Product",
                "Cloud",
                "Early Career",
            ]
    if locations is None:
        locations = _default_brazil_locations()

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
            except (OSError, ValueError, RuntimeError) as exc:
                sys.stderr.write(f"google_careers: page fetch failed: {exc}\n")

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
        if not (_is_brazil_location(loc_str) or "remote" in loc_lower):
            continue

        # Ignora áreas fora do perfil quando nenhum termo configurado casa com o título
        t_lower = title.lower()
        profile_lower = [t.lower() for t in profile_kws]
        if (
            any(
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
            )
            and not any(pt in t_lower for pt in profile_lower)
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
            accept_sen=accept_sen,
            profile_ans=profile_ans,
        )

        signals: dict = {}
        if posting_signals:
            try:
                signals = posting_signals.analyse(
                    f"{title}\n{loc_str}\n{full_desc}",
                    title=title,
                    accept=accept_sen,
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
