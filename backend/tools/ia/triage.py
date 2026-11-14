"""Triagem rápida de vagas, classificação de posts de recrutadores e sorteio de palavras-chave."""

from __future__ import annotations

import hashlib
import itertools
import random
import re
import unicodedata
from typing import Any

from ._facade import facade, painel_perfil, posting_signals, rank_state

_CALIBRATION_ANCHORS = """CALIBRAÇÃO POR ÂNCORAS (USE COMO REFERÊNCIA DE NOTA):
- Âncora A (Júnior/Pleno aderente com stack principal e local/remoto compatível): technical ~86, experience ~88, behavioral ~80, career ~88 -> nota ponderada ~86 (Strong Fit).
- Âncora B (Júnior/Pleno/New Grad com base sólida no ecossistema pedindo tecnologia/framework irmão equivalente na mesma área): technical ~72, experience ~80, behavioral ~75, career ~78 -> nota ~76 (Strong/Good Fit); registre a adaptação em gaps SEM aplicar teto 55.
- Âncora C (Vaga Sênior/Lead/Staff ou 5+ anos exclusivos sem trilha Júnior/Pleno, mesmo com stack idêntica): technical ~85, experience <= 20, behavioral ~70, career <= 35 -> teto máximo 45 (Weak Fit)."""

_LOW_YIELD_SEARCH_TERMS: set[str] = {
    "css3",
    "html5",
    "git",
    "github",
    "gitlab",
    "office",
    "pacote office",
    "excel básico",
    "componentes reutilizáveis",
    "componentes reutilizaveis",
    "visualização",
    "visualizacao",
}


_LOCATION_STOPWORDS: set[str] = {
    "com", "para", "por", "em", "na", "no", "das", "dos", "de", "da", "do",
    "remoto", "hibrido", "presencial", "apenas", "somente", "aceito", "regiao",
    "metropolitana", "cidade", "estado", "local", "ou",
}

_STATE_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("sp", "sao paulo"),
    ("mg", "minas gerais"),
    ("rj", "rio de janeiro"),
    ("rs", "rio grande do sul", "porto alegre"),
    ("pr", "parana", "curitiba"),
    ("sc", "santa catarina", "florianopolis"),
    ("ba", "bahia", "salvador"),
    ("pe", "pernambuco", "recife"),
    ("ce", "ceara", "fortaleza"),
    ("df", "distrito federal", "brasilia"),
    ("go", "goias", "goiania"),
    ("es", "espirito santo", "vitoria"),
    ("bh", "belo horizonte"),
)


def _norm_loc_text(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", stripped.lower()).strip()


def _matches_accepted_location(location_text: str, accepted_locais: str) -> bool:
    """Verifica dinamicamente se uma localidade explícita casa com praças/regiões do perfil."""
    loc = _norm_loc_text(location_text)
    if not loc or any(x in loc for x in ("nao informad", "not specified", "unstated", "brasil", "brazil")):
        return True
    if any(x in loc for x in ("remoto", "remote", "home office", "teletrabalho", "anywhere", "latam", "global", "worldwide")):
        return True

    acc = _norm_loc_text(accepted_locais)
    if not acc:
        return False

    # 1. Tokens explícitos (cidades, bairros, países ou termos compostos informados no perfil)
    raw_chunks = [c.strip() for c in re.split(r"[,;\n/|()]+", acc) if c.strip()]
    phrase_tokens: list[str] = []
    short_codes: set[str] = set()
    for chunk in raw_chunks:
        cleaned = re.sub(r"\s+", " ", chunk.strip(" -.")).strip()
        if not cleaned or cleaned in _LOCATION_STOPWORDS:
            continue
        if len(cleaned) == 2 and cleaned.isalpha():
            short_codes.add(cleaned)
        elif len(cleaned) >= 3:
            phrase_tokens.append(cleaned)
        for sub in re.split(r"\s+-\s+|\s+", cleaned):
            sub_c = sub.strip(" -.")
            if len(sub_c) == 2 and sub_c.isalpha() and sub_c not in _LOCATION_STOPWORDS:
                short_codes.add(sub_c)
            elif len(sub_c) >= 4 and sub_c not in _LOCATION_STOPWORDS:
                phrase_tokens.append(sub_c)

    # 2. Expande apenas os estados/aliases realmente mencionados nas preferências
    for group in _STATE_ALIAS_GROUPS:
        if any(
            (len(g) == 2 and re.search(rf"(?:^|[\s,\-/]){g}(?:$|[\s,\-/])", acc))
            or (len(g) > 2 and g in acc)
            for g in group
        ):
            for alias in group:
                if len(alias) == 2:
                    short_codes.add(alias)
                else:
                    phrase_tokens.append(alias)

    for tok in phrase_tokens:
        if re.search(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", loc):
            return True
    for code in short_codes:
        if re.search(rf"(?:^|[\s,\-/]){re.escape(code)}(?:$|[\s,\-/])", loc):
            return True
    return False


def _extract_subscores_dict(data: Any) -> dict[str, int]:
    """Extrai as 4 subnotas canônicas da rubrica quando todas forem fornecidas pela IA."""
    if not isinstance(data, dict):
        return {}
    raw = data.get("subscores")
    if not isinstance(raw, dict):
        return {}
    keys = ("technical", "experience", "behavioral", "career")
    parsed: dict[str, int] = {}
    for k in keys:
        val = raw.get(k)
        if val is None or isinstance(val, bool):
            return {}
        try:
            parsed[k] = max(0, min(100, int(round(float(val)))))
        except (TypeError, ValueError):
            return {}
    return parsed


def _normalize_gates_dict(raw_gates: Any) -> dict[str, str]:
    """Normaliza o bloco opcional de gates retornado pela IA."""
    g = raw_gates if isinstance(raw_gates, dict) else {}
    elig = str(g.get("eligibility") or "PASS").strip().upper()
    if elig not in ("PASS", "FAIL_INTERNAL", "FAIL_AFFIRMATIVE", "FAIL_VISA", "FLAG"):
        elig = "PASS"
    lang = str(g.get("language") or "PASS").strip().upper()
    if lang not in ("PASS", "FLAG", "FAIL"):
        lang = "PASS"
    loc = str(g.get("location") or "PASS").strip().upper()
    if loc not in ("PASS", "FLAG", "FAIL"):
        loc = "PASS"
    lang_note = str(g.get("language_note") or "").strip()[:240]
    return {
        "eligibility": elig,
        "language": lang,
        "location": loc,
        "language_note": lang_note,
    }


def _apply_seniority_ceiling(
    title: str,
    signals: Any,
    score: int,
    verdict: str,
    summary: str,
) -> tuple[int, str, str]:
    """Trava determinística de segurança para senioridade acima da faixa-alvo."""
    rules = facade()._load_candidate_triage_rules()
    accept_set = set(rules.get("accept_seniority") or ["junior", "pleno"])

    title_str = (title or "").lower()
    sig = signals if isinstance(signals, dict) else {}
    sig_levels = sig.get("seniority") or []
    sig_mismatch = sig.get("seniority_verdict") == "mismatch"
    body_has_accessible = bool(sig.get("body_has_accessible_level"))
    min_years = sig.get("min_years_required")

    senior_title_pat = r"\b(senior|sênior|sr\.?|tech lead|staff|principal|head|engineering manager|gerente|coordenador|diretor|vp)\b"
    if "especialista" not in accept_set:
        senior_title_pat = r"\b(senior|sênior|sr\.?|especialista|tech lead|staff|principal|head|engineering manager|gerente|coordenador|diretor|vp)\b"
    is_senior_title = bool(re.search(senior_title_pat, title_str))
    has_accessible_level = bool(
        re.search(r"\b(junior|júnior|jr\.?|pleno|mid|mid-level|new grad|entry|est[aá]gio|intern|trainee)\b", title_str)
    )

    above_levels = {"senior", "staff", "lead", "gestao"}
    if "especialista" not in accept_set:
        above_levels.add("especialista")
    above_levels -= accept_set

    years_mismatch = isinstance(min_years, (int, float)) and min_years >= 5 and ("senior" not in accept_set)
    body_mismatch = (sig_mismatch and any(lvl in above_levels for lvl in sig_levels)) or years_mismatch

    triggered = (is_senior_title and not has_accessible_level) or (
        body_mismatch and not has_accessible_level and not body_has_accessible
    )
    if triggered and score > 45:
        score = 45
        verdict = "Weak Fit"
        if "senior" not in summary.lower() and "sênior" not in summary.lower() and "anos" not in summary.lower():
            summary = f"A vaga exige senioridade Sênior/Liderança acima da faixa atual do perfil. {summary}"[:600]
    return score, verdict, summary


def _apply_deterministic_gates(
    *,
    title: str = "",
    signals: Any = None,
    score: int,
    verdict: str,
    summary: str = "",
    gates: dict[str, Any] | None = None,
    location: str = "",
    guard_verdict: str = "",
) -> dict[str, Any]:
    """Aplica travas determinísticas de elegibilidade, idioma, localidade e senioridade."""
    f = facade()
    sig = signals if isinstance(signals, dict) else {}
    norm_gates = f._normalize_gates_dict(gates)
    rules = f._load_candidate_triage_rules()

    final_score = max(0, min(100, int(score)))
    final_summary = str(summary or "").strip()
    loc_verdict = norm_gates["location"]
    lang_gate = norm_gates["language"]
    lang_note = norm_gates["language_note"]
    elig_gate = norm_gates["eligibility"]
    gate_reasons: list[str] = []

    if sig.get("internal") or elig_gate == "FAIL_INTERNAL":
        final_score = min(final_score, 15)
        loc_verdict = "FAIL"
        gate_reasons.append("Seleção interna exclusiva para colaboradores atuais (teto 15).")

    if sig.get("affirmative_exclusive") or elig_gate == "FAIL_AFFIRMATIVE":
        final_score = min(final_score, 25)
        gate_reasons.append("Vaga exclusiva de ação afirmativa fora do perfil declarado (teto 25).")

    if elig_gate == "FAIL_VISA":
        final_score = min(final_score, 20)
        loc_verdict = "FAIL"
        gate_reasons.append("Restrição de cidadania/visto incompatível sem elegibilidade remota (teto 20).")

    if lang_gate == "FAIL":
        final_score = min(final_score, 25)
        msg = f"Idioma eliminatório: {lang_note} (teto 25)." if lang_note else "Idioma eliminatório fora do perfil declarado (teto 25)."
        gate_reasons.append(msg)
    elif lang_gate == "FLAG":
        if not lang_note:
            lang_note = "Exigência de idioma avançado/não confirmado no perfil."

    workplace = str(sig.get("workplace") or "")
    wp_evidence = " ".join(str(x) for x in (sig.get("workplace_evidence") or []))
    if workplace == "remote_restricted":
        restricted_foreign = bool(
            re.search(r"\b(us[- ]only|united states only|eu only|uk only|canada only|citizenship|work permit|work authorization)\b", wp_evidence, re.I)
        )
        allows_br_global = bool(
            re.search(r"\b(brazil|brasil|latam|global|worldwide|anywhere|remote from anywhere)\b", wp_evidence + " " + location, re.I)
        )
        if restricted_foreign and not allows_br_global:
            loc_verdict = "FAIL"
    elif workplace == "onsite" and location and not f._matches_accepted_location(location, rules.get("locais") or ""):
        loc_verdict = "FAIL"

    if loc_verdict == "FAIL":
        final_score = min(final_score, 35)
        gate_reasons.append("Localidade ou modalidade incompatível com as praças/remoto do perfil (teto 35).")
    elif loc_verdict == "FLAG":
        final_score = min(final_score, 48)
        gate_reasons.append("Localidade ou remoto restrito/ambíguo exige confirmação (teto 48).")

    before_sen = final_score
    sen_score, _, final_summary = f._apply_seniority_ceiling(
        title, sig, final_score, verdict, final_summary
    )
    capped_by_seniority = sen_score < before_sen
    final_score = min(final_score, sen_score)
    if capped_by_seniority:
        gate_reasons.append("Senioridade/experiência exigida acima da faixa-alvo do perfil (teto 45).")

    final_verdict = "Weak Fit" if (capped_by_seniority and final_score == 45) else rank_state.band(final_score)

    if gate_reasons and gate_reasons[0].split(" (")[0].lower() not in final_summary.lower():
        final_summary = f"{gate_reasons[0]} {final_summary}".strip()[:600]

    guard_alert = ""
    if guard_verdict and "clean" not in guard_verdict.lower():
        guard_alert = guard_verdict[:160]

    return {
        "score": final_score,
        "verdict": final_verdict,
        "summary": final_summary or "Triagem concluída.",
        "location_verdict": loc_verdict,
        "language_gate": lang_gate,
        "language_note": lang_note,
        "eligibility": elig_gate,
        "gate_reasons": gate_reasons,
        "guard_alert": guard_alert,
    }


def _clean_short_bullets(items: Any, limit: int = 3) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for raw in items:
        s = re.sub(r"\s+", " ", str(raw or "").strip(" -•*"))
        if s:
            out.append(s[:180])
        if len(out) >= limit:
            break
    return out


def _finalize_triage_result(
    data: dict[str, Any],
    *,
    title: str,
    signals: Any,
    location: str = "",
    guard_verdict: str = "",
    require_score: bool = True,
) -> dict[str, Any]:
    """Calcula nota oficial ponderada (30/25/15/30), aplica gates/tetos e extrai explicabilidade."""
    f = facade()
    subscores = _extract_subscores_dict(data)
    if subscores:
        raw_score = rank_state.overall_score(subscores)
        raw_verdict = rank_state.band(raw_score)
    elif require_score:
        raw_score = f._parse_strict_score(data)
        raw_verdict = str(data.get("verdict") or rank_state.band(raw_score))[:40]
    else:
        raw_score = 0
        raw_verdict = "Poor Fit"

    raw_summary = str(data.get("summary") or "Triagem concluída.")[:600]
    strengths = _clean_short_bullets(data.get("strengths"), limit=3)
    gaps = _clean_short_bullets(data.get("gaps"), limit=3)

    if not require_score:
        return {
            "score": 0,
            "verdict": "Poor Fit",
            "summary": raw_summary,
            "subscores": {},
            "location_verdict": "PASS",
            "language_gate": "PASS",
            "language_note": "",
            "strengths": strengths,
            "gaps": gaps,
            "guard_alert": "",
        }

    gated = f._apply_deterministic_gates(
        title=title,
        signals=signals,
        score=raw_score,
        verdict=raw_verdict,
        summary=raw_summary,
        gates=data.get("gates"),
        location=location,
        guard_verdict=guard_verdict,
    )
    for reason in gated["gate_reasons"]:
        if not any(reason[:24].lower() in g.lower() for g in gaps):
            gaps.insert(0, reason)
    if gated["language_gate"] == "FLAG" and gated["language_note"]:
        flag_line = f"Idioma: {gated['language_note']}"
        if not any("idioma" in g.lower() for g in gaps):
            gaps.append(flag_line)

    return {
        "score": gated["score"],
        "verdict": gated["verdict"],
        "summary": gated["summary"],
        "subscores": subscores,
        "location_verdict": gated["location_verdict"],
        "language_gate": gated["language_gate"],
        "language_note": gated["language_note"],
        "strengths": strengths[:3],
        "gaps": gaps[:4],
        "guard_alert": gated["guard_alert"],
    }


def _render_quick_eval_md(url: str, portal: str, ai_model: str, res: dict[str, Any]) -> str:
    """Serializa resultado estruturado da triagem rápida no cache `{h}_avaliacao.md`."""
    lines = [
        f"## Triagem rápida: {portal or 'vaga'}",
        "",
        f"**Nota geral: {res['score']}/100**",
        f"### Veredito: {res['verdict']}",
        "",
        f"**Modelo IA:** {ai_model}",
    ]
    subs = res.get("subscores") or {}
    if len(subs) == 4:
        lines.extend([
            "",
            "### Subnotas da rubrica (30/25/15/30)",
            f"- Técnica (30%): {subs['technical']}/100",
            f"- Experiência (25%): {subs['experience']}/100",
            f"- Comportamental (15%): {subs['behavioral']}/100",
            f"- Carreira (30%): {subs['career']}/100",
            f"- Local e Modalidade: {res.get('location_verdict') or 'PASS'}",
            f"- Filtro de idioma: {res.get('language_gate') or 'PASS'}"
            + (f" ({res['language_note']})" if res.get("language_note") else ""),
        ])
    elif res.get("location_verdict") in ("FLAG", "FAIL") or res.get("language_gate") in ("FLAG", "FAIL"):
        lines.extend([
            "",
            "### Gates",
            f"- Local e Modalidade: {res.get('location_verdict') or 'PASS'}",
            f"- Filtro de idioma: {res.get('language_gate') or 'PASS'}"
            + (f" ({res['language_note']})" if res.get("language_note") else ""),
        ])
    if res.get("strengths"):
        lines.extend(["", "### Pontos fortes"] + [f"- {s}" for s in res["strengths"]])
    if res.get("gaps"):
        lines.extend(["", "### Lacunas e Riscos"] + [f"- {g}" for g in res["gaps"]])
    if res.get("guard_alert"):
        lines.extend(["", f"**Alerta de segurança:** {res['guard_alert']}"])
    lines.extend(["", "### Resumo da triagem rápida", str(res.get("summary") or ""), "", f"URL: {url}", ""])
    return "\n".join(lines)


def triar_vaga_rapida(url: str, job_data: dict | None = None) -> dict:
    """Triagem rápida com rubrica decomposta (30/25/15/30), gates e cálculo determinístico."""
    f = facade()
    posting = f.fetch_posting(url, job_data)
    raw_text = posting.get("text") or ""
    lang = f._detect_language(raw_text)
    perfil = f._compact_candidate_profile(language=lang, max_chars=9500)

    prompt_head = f"""Você é o triador rigoroso de vagas do Vagamundo. Avalie o encaixe real entre o perfil e a vaga usando SOMENTE fatos do perfil.

RUBRICA OFICIAL (SUBNOTAS 0..100 E PESOS CANÔNICOS):
1. `technical` (30%): aderência à stack principal, fundamentos e entregas comprovadas (NÃO restrinja a versão específica; em níveis Júnior/Pleno/New Grad, trate frameworks irmãos dentro de ecossistema já dominado como transferíveis na faixa 68–80 sem aplicar punição de stack ausente; reserve <= 40 apenas quando stack central exclusiva estiver totalmente ausente do perfil).
2. `experience` (25%): senioridade e tempo real de experiência vs `Senioridade-alvo` do perfil. Se exigir Sênior/5+ anos/Tech Lead/Staff/Gerência sem trilha Júnior/Pleno paralela, atribua `experience` <= 25 (isso ativa o teto rígido 45 Weak Fit).
3. `behavioral` (15%): autonomia, colaboração e práticas de engenharia exigidas (quando pouco detalhado no anúncio, base neutra 70 para vagas aderentes).
4. `career` (30%): alinhamento de cargo, modelo/localidade, regime e idiomas aceitos no perfil.

GATES DE ELEGIBILIDADE (EXTRAIA EVIDÊNCIA LITERAL ANTES DE PONTUAR):
- `eligibility`: `FAIL_INTERNAL` (vaga interna p/ funcionários), `FAIL_AFFIRMATIVE` (exclusiva ação afirmativa sem enquadramento no perfil), `FAIL_VISA` (cidadania/visto local sem patrocínio ou remoto Brasil), `FLAG` (dúvida relevante) ou `PASS`.
- `language`: `FAIL` (exige fluentemente idioma que o candidato NÃO possui), `FLAG` (inglês avançado/C1 não totalmente confirmado ou exigência mista) ou `PASS`; preencha `language_note` quando `FLAG` ou `FAIL`.
- `location`: `FAIL` (presencial/híbrido confirmado fora das praças aceitas ou remoto restrito ex.: US/EU-only sem remoto Brasil/Global), `FLAG` (remoto com visitas ou local incerto) ou `PASS`.

{_CALIBRATION_ANCHORS}

Retorne APENAS um objeto JSON válido neste formato:
{{"model": "<nome do modelo>", "evidence": {{"seniority": "...", "location_mode": "...", "language_req": "..."}}, "gates": {{"eligibility": "PASS", "language": "PASS", "language_note": "", "location": "PASS"}}, "subscores": {{"technical": 78, "experience": 82, "behavioral": 75, "career": 80}}, "strengths": ["ponto forte 1"], "gaps": ["lacuna 1"], "score": 79, "verdict": "Strong Fit", "summary": "Duas frases diretas: o que casa e a principal lacuna ou gate."}}

PERFIL DA PESSOA CANDIDATA:
"""
    budget = f._prompt_posting_budget(len(prompt_head) + 250, len(perfil), hard_cap=7500)
    vaga_compacta = f._compact_posting_text(raw_text, max_chars=budget)
    prompt = f"{prompt_head}{perfil}\n\n{f._vaga_block(vaga_compacta)}\n"

    with f._json_mode():
        data = f._json_object(f.call_llm(prompt, temperature=0.1))
    ai_model = f._extract_ai_model(data)

    jdata = posting.get("job_data") or job_data or {}
    signals = posting.get("signals") or (jdata.get("signals") if isinstance(jdata, dict) else {}) or {}
    res = f._finalize_triage_result(
        data,
        title=posting.get("title") or (jdata.get("title") if isinstance(jdata, dict) else "") or "",
        signals=signals,
        location=(jdata.get("location") if isinstance(jdata, dict) else "") or "",
        guard_verdict=posting.get("guard_verdict") or "",
        require_score=True,
    )

    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    eval_file = f.PAINEL_DIR / f"{h}_avaliacao.md"
    eval_file.parent.mkdir(parents=True, exist_ok=True)
    if not eval_file.exists() or eval_file.read_text(encoding="utf-8").startswith("## Triagem rápida"):
        eval_file.write_text(
            f._render_quick_eval_md(url, posting.get("portal") or "vaga", ai_model, res),
            encoding="utf-8",
        )
    return {
        "url": url,
        "score": res["score"],
        "verdict": res["verdict"],
        "summary": res["summary"],
        "ai_model": ai_model,
        "title": posting.get("title", ""),
        "company": posting.get("company", ""),
        "subscores": res["subscores"],
        "location_verdict": res["location_verdict"],
        "language_gate": res["language_gate"],
        "language_note": res["language_note"],
        "strengths": res["strengths"],
        "gaps": res["gaps"],
        "guard_alert": res["guard_alert"],
    }


def _parse_strict_score(data: Any) -> int:
    """Valida e extrai nota numérica 0..100 sem fallback silencioso para 50."""
    raw_score = data.get("score") if isinstance(data, dict) else None
    if raw_score is None or isinstance(raw_score, bool):
        raise ValueError("A IA não retornou uma nota numérica válida ('score') na triagem.")
    try:
        return max(0, min(100, int(raw_score)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Nota inválida retornada pela IA: {raw_score!r}") from exc


def _normalize_recruiter_classification(raw: Any) -> str:
    """Normaliza a categoria retornada pela IA para um dos 3 valores válidos."""
    key = re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())
    aliases = {
        "vaga_ativa": "vaga_ativa",
        "vaga": "vaga_ativa",
        "vaga_real": "vaga_ativa",
        "vaga_aberta": "vaga_ativa",
        "banco_talentos": "banco_talentos",
        "banco_de_talentos": "banco_talentos",
        "talent_pool": "banco_talentos",
        "nao_e_vaga": "nao_e_vaga",
        "não_é_vaga": "nao_e_vaga",
        "nao_vaga": "nao_e_vaga",
        "not_a_job": "nao_e_vaga",
    }
    if key in aliases:
        return aliases[key]
    raise ValueError(f"Classificação inválida retornada pela IA: {raw!r}")


def triar_post_recrutador(post_data: dict) -> dict[str, Any]:
    """Classifica publicação com e-mail direto, roda guard/signals, extrai rubrica e aplica travas."""
    if not isinstance(post_data, dict):
        raise ValueError("post_data inválido para triagem de recrutador.")
    f = facade()

    title = str(post_data.get("title") or "").strip()
    company = str(post_data.get("company") or "").strip()
    location = str(post_data.get("location") or "Não informada").strip()
    work_model = str(post_data.get("work_model") or "Não informado").strip()
    emails = [str(e).strip().lower() for e in (post_data.get("emails") or []) if str(e).strip()]
    raw_desc = str(post_data.get("description") or "").strip()

    clean_desc, guard_findings = f._apply_posting_guard(raw_desc)
    rules = f._load_candidate_triage_rules()
    signals = post_data.get("signals")
    if not isinstance(signals, dict):
        signals = posting_signals.analyse(clean_desc, title=title, accept=rules["accept_seniority"])
        signals["verdict"] = posting_signals.verdict(signals)

    guard_verdict = str(guard_findings.get("verdict") or "")
    header = f._format_structured_header({
        "title": title,
        "company": company,
        "location": location,
        "work_model": work_model,
        "signals": signals,
        "guard_verdict": guard_verdict,
    })
    raw_body = (
        f"{header}"
        f"E-mails extraídos: {', '.join(emails) or 'nenhum'}\n\n"
        f"{clean_desc}"
    )
    lang = f._detect_language(raw_body)
    perfil = f._compact_candidate_profile(language=lang, max_chars=9500)

    prompt_head = f"""Você é o triador rigoroso de publicações de recrutadores do Vagamundo.
Analise a publicação coletada e classifique em EXATAMENTE UMA categoria, identifique o e-mail de recrutamento e avalie o encaixe real com o perfil usando SOMENTE fatos do perfil.

CATEGORIAS OBRIGATÓRIAS ("classification"):
1. `"vaga_ativa"`: existe uma vaga específica aberta com contratação real descrita no texto.
2. `"banco_talentos"`: captação genérica sem vaga específica aberta (ex.: "envie seu CV para futuras oportunidades", "banco de talentos", "talentos em geral").
3. `"nao_e_vaga"`: NÃO é uma vaga de emprego (ex.: artigo, dica de carreira, evento, divulgação/spam, nota de suporte/SAC/LGPD/dpo@, post pedindo indicação de serviço ou sem processo seletivo).

REGRAS E RUBRICA PARA `"vaga_ativa"` (SUBNOTAS `technical` 30%, `experience` 25%, `behavioral` 15%, `career` 30%):
- **Múltiplas vagas no mesmo anúncio:** se a publicação listar 2 ou mais cargos/trilhas (ex.: Backend Rust e Machine Learning Python/Frontend Júnior), avalie e pontue considerando a vaga com **MAIOR aderência** ao perfil (não penalize o post por requisitos exclusivos de uma segunda trilha).
- Se exigir exclusivamente senioridade acima da faixa-alvo do perfil (Sênior/5+ anos, Lead, Staff, Principal, Founding sênior ou Gerência quando não houver abertura Júnior/Pleno/New Grad compatível), atribua `experience` <= 25 (teto máximo **45 "Weak Fit"**).
- Se exigir especialidade ou ecossistema central totalmente ausente do perfil como requisito exclusivo (quando não houver base equivalente compatível), teto máximo é **55**. Porém, em vagas Júnior, Pleno ou equivalentes que peçam uma ferramenta ou framework irmão dentro de um ecossistema já dominado pelo perfil, não aplique teto 55: pontue na faixa **65–78** sinalizando a adaptação necessária em `gaps` e no resumo.
- Avalie também os gates `eligibility` (`PASS | FAIL_INTERNAL | FAIL_AFFIRMATIVE | FAIL_VISA | FLAG`), `language` (`PASS | FLAG | FAIL`) + `language_note`, e `location` (`PASS | FLAG | FAIL` — presencial/híbrida fora das praças aceitas ou remota restrita US/EU-only -> `FAIL`).
- Se for `"banco_talentos"` ou `"nao_e_vaga"`, retorne `"score": 0`, `"verdict": "Poor Fit"` e subnotas zeradas.

{_CALIBRATION_ANCHORS}

E-MAIL PRINCIPAL ("best_email"):
- Dentre os `E-mails extraídos`, escolha o endereço de recrutamento voltado a recebimento de currículos.
- Se não houver e-mail extraído (ex.: publicação de vaga no LinkedIn com link/contato direto na rede) ou nenhum for de recrutamento (apenas SAC, DPO, abuso, suporte), retorne `""` — mas mantenha `"classification": "vaga_ativa"` normalmente se houver uma vaga real descrita.

Retorne APENAS um objeto JSON neste formato:
{{"model": "<nome do modelo>", "classification": "vaga_ativa", "best_email": "rh@empresa.com", "evidence": {{"seniority": "...", "location_mode": "...", "language_req": "..."}}, "gates": {{"eligibility": "PASS", "language": "PASS", "language_note": "", "location": "PASS"}}, "subscores": {{"technical": 78, "experience": 80, "behavioral": 75, "career": 78}}, "strengths": ["ponto forte"], "gaps": ["lacuna ou adaptação"], "score": 78, "verdict": "Good Fit", "summary": "Duas frases objetivas em português explicando a classificação e o principal ponto forte ou lacuna."}}

PERFIL DA PESSOA CANDIDATA:
"""
    budget = f._prompt_posting_budget(len(prompt_head) + 250, len(perfil), hard_cap=7500)
    body_compact = f._compact_posting_text(raw_body, max_chars=budget)
    prompt = f"{prompt_head}{perfil}\n\n{f._tagged_block('PUBLICACAO', 'CONTEÚDO DA PUBLICAÇÃO COLETADA', body_compact)}\n"

    with f._json_mode():
        data = f._json_object(f.call_llm(prompt, temperature=0.1))
    if not isinstance(data, dict) or not data:
        raise ValueError("A IA não retornou JSON válido na triagem do recrutador.")

    ai_model = f._extract_ai_model(data)
    classification = f._normalize_recruiter_classification(data.get("classification"))
    raw_best = str(data.get("best_email") or "").strip().lower()
    best_email = raw_best if ("@" in raw_best and "." in raw_best.split("@", 1)[1]) else ""
    if not best_email and classification == "vaga_ativa" and len(emails) == 1:
        best_email = emails[0]

    res = f._finalize_triage_result(
        data,
        title=title,
        signals=signals,
        location=location,
        guard_verdict=guard_verdict,
        require_score=(classification == "vaga_ativa"),
    )

    return {
        "classification": classification,
        "best_email": best_email,
        "score": res["score"],
        "verdict": res["verdict"],
        "summary": res["summary"],
        "ai_model": ai_model,
        "subscores": res["subscores"],
        "location_verdict": res["location_verdict"],
        "language_gate": res["language_gate"],
        "language_note": res["language_note"],
        "strengths": res["strengths"],
        "gaps": res["gaps"],
        "guard_alert": res["guard_alert"],
    }


def _sanitize_search_keywords(items: list[Any], limit: int = 2) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for raw in items:
        kw = re.sub(r"[\"'()\[\],;]+", " ", str(raw or "")).strip()
        kw = re.sub(r"\s+", " ", kw)
        if len(kw) < 2 or kw.lower() in seen:
            continue
        seen.add(kw.lower())
        clean.append(kw[:45])
        if len(clean) >= limit:
            break
    return clean


def _pair_key(items: list[str]) -> str:
    return "|".join(sorted(str(x).strip().lower() for x in items if str(x).strip()))


def _fallback_cv_keywords(avoid_recent: list[str] | None = None, limit: int = 2, mode: str = "jobs") -> list[str]:
    raw_avoid = [str(x).strip().lower() for x in (avoid_recent or []) if str(x).strip()]
    if limit <= 1:
        raw_avoid = [re.split(r"[,|]+", x)[0].strip() for x in raw_avoid if re.split(r"[,|]+", x)[0].strip()][-10:]
    avoid_strings = set(raw_avoid)
    avoid_pairs: set[str] = set()
    for raw in avoid_strings:
        parts = [p.strip().lower() for p in re.split(r"[,|]+", raw) if p.strip()]
        if parts:
            avoid_pairs.add("|".join(sorted(parts[:limit])))

    areas = painel_perfil.extract_cv_areas() or []
    candidate_pairs: list[list[str]] = []
    atomic_tokens: list[str] = []
    seen_tokens: set[str] = set()

    for a in areas:
        raw_kws = a.get("keywords") or []
        if mode == "recruiters":
            raw_kws = [
                re.sub(
                    r"^(?:desenvolvedor(?:a)?|programador(?:a)?|engenheir[oa]|developer|engineer)\s+",
                    "",
                    str(k).strip(),
                    flags=re.IGNORECASE,
                ).strip()
                for k in raw_kws
            ]
        kws = [
            k
            for k in _sanitize_search_keywords(raw_kws, limit=6)
            if k.lower() not in _LOW_YIELD_SEARCH_TERMS
        ]
        if not kws:
            continue
        if limit <= 1:
            for kw in kws:
                candidate_pairs.append([kw])
        elif len(kws) >= 2:
            for combo in itertools.combinations(kws, min(limit, len(kws))):
                candidate_pairs.append(list(combo))
        else:
            candidate_pairs.append(kws[:limit])
        for tok in kws:
            norm = tok.lower()
            if norm not in seen_tokens:
                seen_tokens.add(norm)
                atomic_tokens.append(tok)

    if limit <= 1 and atomic_tokens:
        for tok in atomic_tokens:
            candidate_pairs.append([tok])
    elif limit == 2 and len(atomic_tokens) >= 2:
        max_cross = 60 if mode == "recruiters" else 30
        cross_pairs = [[a_kw, b_kw] for a_kw, b_kw in itertools.combinations(atomic_tokens[:14], 2)]
        random.shuffle(cross_pairs)
        candidate_pairs.extend(cross_pairs[:max_cross])

    unique_pairs: list[list[str]] = []
    seen_pair_keys: set[str] = set()
    for pair in candidate_pairs:
        pk = _pair_key(pair)
        if not pk or pk in seen_pair_keys:
            continue
        seen_pair_keys.add(pk)
        unique_pairs.append(pair)

    unused = [
        p
        for p in unique_pairs
        if ", ".join(p).lower() not in avoid_strings
        and " ".join(p).lower() not in avoid_strings
        and _pair_key(p) not in avoid_pairs
    ]
    pool = unused or unique_pairs
    if pool:
        return random.choice(pool)[:limit]
    return []


def sortear_palavras_chave_busca(
    avoid_recent: list[str] | None = None,
    region: str = "all",
    mode: str = "jobs",
    limit: int | None = None,
) -> dict[str, Any]:
    """Usa a IA para sortear 1 (padrão recrutadores/automático) ou até 2 palavras-chave de busca baseadas no currículo."""
    f = facade()
    n_terms = max(1, min(2, int(limit))) if limit is not None else (1 if mode == "recruiters" else 2)
    profile_text = f._compact_candidate_profile(language="pt", max_chars=9000)
    raw_avoid = [str(x).strip() for x in (avoid_recent or []) if str(x).strip()]
    if n_terms == 1:
        avoid_list = [re.split(r"[,|]+", x)[0].strip() for x in raw_avoid if re.split(r"[,|]+", x)[0].strip()][-10:]
    else:
        avoid_list = raw_avoid[-20:]
    avoid_block = " | ".join(avoid_list[-10:]) if avoid_list else "nenhum"
    region_hint = (
        "portais no Brasil (pt-BR ou termos técnicos usuais)"
        if region == "brasil"
        else ("portais internacionais/remotos" if region in ("estados-unidos", "europa", "global", "remote") else "portais variados")
    )
    atomic_rule = (
        "- OBRIGATÓRIO para recrutadores: sorteie SOMENTE termos principais da área do perfil com alto volume de vagas (1 a 2 palavras bilíngues PT/EN presentes no perfil/currículo); NUNCA use prefixos genéricos ('Desenvolvedor', 'Developer', 'Analista') nem utilitários secundários isolados."
        if mode == "recruiters"
        else (
            "- Prefira termos principais, tecnologias ou especialidades diretamente ligadas ao perfil que aparecem em títulos e tags de vagas PT/EN (1 a 2 palavras), evitando utilitários secundários isolados ou títulos longos."
            if region == "all" or n_terms == 1
            else "- Escolha termos realmente presentes ou diretamente ligados às competências/cargos do perfil (ex.: uma especialidade principal e um cargo/foco)."
        )
    )
    qty_header = (
        f"sorteie EXATAMENTE 1 palavra-chave curta e eficaz para buscar novas vagas agora em {region_hint}."
        if n_terms == 1
        else f"sorteie no MÁXIMO 2 palavras-chave curtas e eficazes para buscar novas vagas agora em {region_hint}."
    )
    qty_rule = (
        "- Retorne exatamente 1 termo no array `keywords` (1 a 2 palavras, sem vírgulas nem operadores booleanos)."
        if n_terms == 1
        else "- Retorne no máximo 2 termos (cada termo com 1 a 3 palavras, sem vírgulas nem operadores booleanos)."
    )
    json_example = (
        '{"keywords": ["termo1"], "rationale": "Frase curta explicando a tecnologia escolhida."}'
        if n_terms == 1
        else '{"keywords": ["termo1", "termo2"], "rationale": "Frase curta explicando o eixo escolhido."}'
    )

    prompt = f"""Com base EXCLUSIVA no currículo e perfil abaixo, {qty_header}

REGRAS:
{qty_rule}
{atomic_rule}
- NÃO repita nenhum destes termos/pares já sorteados recentemente: {avoid_block}.
- Retorne APENAS JSON neste formato:
{json_example}

PERFIL DA PESSOA CANDIDATA:
{profile_text}
"""
    avoid_keys = {
        _pair_key([p.strip() for p in re.split(r"[,|]+", item) if p.strip()][:n_terms])
        for item in avoid_list
    }
    try:
        with f._json_mode():
            data = f._json_object(f.call_llm(prompt, temperature=0.8, timeout=90))
        kws = data.get("keywords") if isinstance(data, dict) else None
        rationale = str(data.get("rationale") or "").strip()[:240] if isinstance(data, dict) else ""
        if isinstance(kws, list):
            cleaned = [
                k
                for k in _sanitize_search_keywords(kws, limit=n_terms)
                if k.lower() not in _LOW_YIELD_SEARCH_TERMS
            ]
            if cleaned:
                if _pair_key(cleaned) not in avoid_keys:
                    return {"keywords": cleaned, "rationale": rationale, "source": "ai"}
                alt = f._fallback_cv_keywords(avoid_recent=avoid_list, limit=n_terms, mode=mode)
                if alt and _pair_key(alt) not in avoid_keys:
                    return {
                        "keywords": alt,
                        "rationale": "Rotação automática para evitar repetição de termos recentes.",
                        "source": "cv_fallback",
                    }
                return {"keywords": cleaned, "rationale": rationale, "source": "ai"}
    except f.ConsentRequired:
        raise
    except Exception:
        pass

    fallback = f._fallback_cv_keywords(avoid_recent=avoid_list, limit=n_terms, mode=mode)
    if not fallback:
        raise ValueError("Não foi possível extrair palavras-chave do seu currículo. Preencha seu perfil primeiro.")
    return {
        "keywords": fallback,
        "rationale": "Selecionada dinamicamente a partir das áreas do seu currículo.",
        "source": "cv_fallback",
    }
