"""A aba "Meu perfil" do painel (tools/painel.py): o começo do /setup em botões.

  * Documentos - o currículo e a exportação do LinkedIn, em PDF, gravados em
                 documents/cv/ e documents/linkedin/ (fora do git), onde o
                 Caminho A do /setup os lê;
  * Formulário - o que o currículo não diz (gênero gramatical, modelo de
                 trabalho, regimes, pretensão, níveis, cargos a buscar...),
                 gravado em documents/perfil/respostas.json (fora do git);
  * Privacidade - para onde o repositório publica, conferido antes de o Claude
                 gravar o perfil em arquivos rastreados pelo git.

Funções puras, testadas sem servidor; quem chama o Claude é o painel.
"""

import base64
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

try:
    from backend.tools import posting_signals as _posting_signals
except ImportError:
    import posting_signals as _posting_signals

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
DOCUMENTS = ROOT / "documents"
LOCAL_PERFIL_DIR = DOCUMENTS / "perfil"
ANSWERS = LOCAL_PERFIL_DIR / "respostas.json"
LOCAL_PROFILE_MD = LOCAL_PERFIL_DIR / "candidate-profile.md"
LOCAL_QUERIES_MD = LOCAL_PERFIL_DIR / "search-queries.md"
PROFILE_MD = REPO_ROOT / ".claude" / "skills" / "job-application-assistant" / "01-candidate-profile.md"

_DEFAULT_REPO_ROOT = REPO_ROOT
_DEFAULT_DOCUMENTS = DOCUMENTS
_DEFAULT_ANSWERS = ANSWERS
_DEFAULT_LOCAL_PROFILE_MD = LOCAL_PROFILE_MD
_DEFAULT_LOCAL_QUERIES_MD = LOCAL_QUERIES_MD
_DEFAULT_PROFILE_MD = PROFILE_MD
_PLACEHOLDER_MARKERS = ("[YOUR_NAME]", "[YOUR_EMAIL]", "[FIRST_NAME]", "[YOUR_CITY]")
UPLOAD_KINDS = {"cv": "cv", "linkedin": "linkedin"}
MAX_UPLOAD = 10_000_000

LEVELS = list(_posting_signals.LEVELS)

# Seções do formulário: (título, campos). Tipos: text, textarea, lines (uma
# entrada por linha, gravada como lista), choice (uma opção), multi (várias).
SCHEMA = [
    ("Perfil e busca", [
        {"key": "cidade", "label": "Cidade e UF", "type": "text", "placeholder": "Campinas - SP"},
        {"key": "idiomas", "label": "Idiomas e nível, um por linha", "type": "lines",
         "placeholder": "Português - nativo\nInglês - avançado",
         "help": "Seja realista: uma vaga que exige um idioma fora desta lista é descartada."},
        {"key": "cargos", "label": "Cargos a buscar, um por linha", "type": "lines",
         "placeholder": "Engenheiro de Software\nDesenvolvedor Full Stack"},
        {"key": "palavras_chave_sorteio",
         "label": "Palavras-chave do currículo para busca e sorteio (Sortear área CV), uma por linha",
         "type": "lines",
         "placeholder": "Python\nGestão de Projetos\nAnálise Financeira\nCloud",
         "help": "Preenchido pela IA a partir do currículo em PDF. Adicione, edite ou remova termos — o botão \"Sortear área CV\" em Buscar Vagas e Recrutadores sorteia exatamente desta lista."},
        {"key": "senioridade", "label": "Níveis que fazem sentido", "type": "multi", "options": LEVELS},
    ]),
    ("Condições e regras", [
        {"key": "modelo", "label": "Modelo de trabalho aceito", "type": "multi", "options": ["remoto", "hibrido", "presencial"]},
        {"key": "locais", "label": "Cidades aceitas para híbrido ou presencial", "type": "text",
         "placeholder": "Ex.: São Paulo, Campinas (vazio se aceitar apenas remoto)"},
        {"key": "regimes", "label": "Regimes aceitos", "type": "multi",
         "options": ["CLT", "PJ", "estagio", "temporario", "freelance"]},
        {"key": "deal_breakers", "label": "O que você não aceita de jeito nenhum (piso salarial, viagem, presencial fora...)",
         "type": "textarea"},
        {"key": "genero", "label": "Nos textos em português, escrever no", "type": "choice",
         "options": ["feminino", "masculino", "neutro"],
         "help": "Feminino: \"formada\"; masculino: \"formado\"; neutro: \"tenho formação em\"."},
    ]),
]
FIELDS = {f["key"]: f for _, fields in SCHEMA for f in fields}


# ---------------------------------------------------------------------------
# Formulário
# ---------------------------------------------------------------------------

def _normalize_lines(value) -> list[str]:
    items = value.splitlines() if isinstance(value, str) else value if isinstance(value, list) else []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, str):
            continue
        item = raw.strip()[:200]
        if item and item.lower() not in seen:
            seen.add(item.lower())
            cleaned.append(item)
        if len(cleaned) >= 30:
            break
    return cleaned


def clean_answers(data: dict) -> dict:
    """Só os campos do formulário, nos tipos certos; o resto é descartado."""
    if not isinstance(data, dict):
        return {}
    # Migração transparente de respostas antigas que usavam `competencias_busca`
    source = dict(data)
    if "palavras_chave_sorteio" not in source and source.get("competencias_busca"):
        source["palavras_chave_sorteio"] = source["competencias_busca"]

    out = {}
    for key, field in FIELDS.items():
        value = source.get(key)
        kind = field["type"]
        if kind in ("text", "textarea", "choice") and isinstance(value, str):
            value = value.strip()[:4000]
            if kind == "choice" and value not in field["options"]:
                continue
            if value:
                out[key] = value
        elif kind == "lines":
            items = _normalize_lines(value)
            if items:
                out[key] = items
        elif kind == "multi":
            items = value.splitlines() if isinstance(value, str) else value if isinstance(value, list) else []
            items = [i.strip()[:200] for i in items if isinstance(i, str) and i.strip()][:30]
            items = [i for i in field["options"] if i in items]
            if items:
                out[key] = items
    return out


def load_answers(path: Path | None = None) -> dict:
    path = path or ANSWERS
    try:
        return clean_answers(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def save_answers(data: dict, path: Path | None = None) -> dict:
    path = path or ANSWERS
    answers = clean_answers(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**answers, "atualizado": datetime.now().isoformat(timespec="seconds")},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return answers


def format_answers(answers: dict) -> str:
    """As respostas como "Pergunta: resposta", para o pedido ao Claude."""
    lines = []
    for _, fields in SCHEMA:
        for f in fields:
            value = answers.get(f["key"])
            if value:
                lines.append(f"{f['label']}: {'; '.join(value) if isinstance(value, list) else value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------

def safe_name(name: str) -> str:
    """Só o nome do arquivo, com letras, números, espaço, ponto, hífen e sublinhado, terminando em .pdf."""
    base = re.sub(r"[^\w.\- ]", "_", Path(str(name).replace("\\", "/")).name).strip(" .")[:100]
    if not base.lower().endswith(".pdf") or len(base) <= 4:
        raise ValueError("envie um arquivo PDF (no Word: Arquivo > Salvar como > PDF)")
    return base[:-4] + ".pdf"


def save_upload(kind: str, name: str, data_b64: str, base: Path | None = None) -> str:
    base = base or DOCUMENTS
    if kind not in UPLOAD_KINDS:
        raise ValueError(f"tipo de documento desconhecido: {kind}")
    name = safe_name(name)
    try:
        raw = base64.b64decode(data_b64 or "", validate=True)
    except (ValueError, TypeError):
        raise ValueError("o arquivo chegou corrompido; tente de novo")
    if len(raw) > MAX_UPLOAD:
        raise ValueError("arquivo grande demais (máximo 10 MB)")
    if not raw.startswith(b"%PDF-"):
        raise ValueError("isto não é um PDF de verdade")
    folder = base / UPLOAD_KINDS[kind]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(raw)
    return name


def list_uploads(base: Path | None = None) -> dict:
    base = base or DOCUMENTS
    out = {}
    for kind, sub in UPLOAD_KINDS.items():
        folder = base / sub
        files = sorted(p for p in folder.glob("*") if p.is_file() and p.name != ".gitkeep") if folder.is_dir() else []
        out[kind] = [{"name": p.name, "size": p.stat().st_size,
                      "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes")} for p in files]
    return out


def remove_upload(kind: str, name: str, base: Path | None = None) -> None:
    """Apaga só um arquivo que a listagem mostra, pelo nome exato."""
    base = base or DOCUMENTS
    if kind not in UPLOAD_KINDS or name not in {f["name"] for f in list_uploads(base)[kind]}:
        raise ValueError("arquivo não encontrado")
    (base / UPLOAD_KINDS[kind] / name).unlink()


def has_documents(base: Path | None = None) -> bool:
    return any(list_uploads(base).values())


# ---------------------------------------------------------------------------
# Privacidade: para onde este repositório publica
# ---------------------------------------------------------------------------

def github_repo(url: str) -> str | None:
    """owner/repo de um remoto do GitHub (https ou ssh), ou None."""
    m = re.match(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def privacy(root: Path | None = None) -> dict:
    """status: local (sem remoto), privado, outro (remoto fora do GitHub), publico ou desconhecido."""
    root = root or REPO_ROOT
    try:
        origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root, capture_output=True,
                                text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        origin = ""
    if not origin:
        return {"status": "local", "repo": None}
    repo = github_repo(origin)
    if not repo:
        return {"status": "outro", "repo": None}
    gh = shutil.which("gh")
    if not gh:
        return {"status": "desconhecido", "repo": repo}
    try:
        proc = subprocess.run([gh, "repo", "view", repo, "--json", "visibility"], capture_output=True,
                              text=True, timeout=20)
        visibility = json.loads(proc.stdout).get("visibility") if proc.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        visibility = None
    status = {"PRIVATE": "privado", "INTERNAL": "privado", "PUBLIC": "publico"}.get(visibility, "desconhecido")
    return {"status": status, "repo": repo}


def needs_confirmation(info: dict) -> bool:
    return info.get("status") in ("publico", "desconhecido")


def is_customized_md(text: str | None) -> bool:
    """True quando o markdown tem conteúdo real (sem marcadores do modelo)."""
    if not text or not text.strip():
        return False
    return not any(marker in text for marker in _PLACEHOLDER_MARKERS)


def local_profile_path() -> Path:
    """Caminho .gitignored para o perfil consolidado local em Markdown."""
    if LOCAL_PROFILE_MD != _DEFAULT_LOCAL_PROFILE_MD:
        return LOCAL_PROFILE_MD
    if ANSWERS != _DEFAULT_ANSWERS:
        return ANSWERS.parent / "candidate-profile.md"
    return DOCUMENTS / "perfil" / "candidate-profile.md"


def local_queries_path() -> Path:
    """Caminho .gitignored para as consultas de busca geradas localmente."""
    if LOCAL_QUERIES_MD != _DEFAULT_LOCAL_QUERIES_MD:
        return LOCAL_QUERIES_MD
    if ANSWERS != _DEFAULT_ANSWERS:
        return ANSWERS.parent / "search-queries.md"
    return DOCUMENTS / "perfil" / "search-queries.md"


def _effective_profile_md() -> Path:
    if PROFILE_MD != _DEFAULT_PROFILE_MD:
        return PROFILE_MD
    return REPO_ROOT / ".claude" / "skills" / "job-application-assistant" / "01-candidate-profile.md"


def _effective_claude_md() -> Path:
    return REPO_ROOT / "CLAUDE.md"


def _read_if_customized(path: Path | None) -> str | None:
    if not path:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text if is_customized_md(text) else None


def _cached_ai_perfil_report() -> str | None:
    perfil_hash = hashlib.sha256(b"perfil").hexdigest()[:16]
    report_path = DOCUMENTS / "applications" / "_painel" / f"{perfil_hash}_perfil.md"
    try:
        if report_path.is_file():
            text = report_path.read_text(encoding="utf-8").strip()
            return text or None
    except OSError:
        pass
    return None


def _has_uploaded_documents() -> bool:
    uploads = list_uploads(DOCUMENTS)
    return any(bool(files) for files in uploads.values())


def sync_local_queries_from_answers(
    answers: dict | None = None,
    *,
    overwrite: bool = False,
) -> Path | None:
    """Gera `backend/documents/perfil/search-queries.md` (.gitignored) a partir do formulário."""
    target = local_queries_path()
    if target.exists() and not overwrite:
        return target
    data = answers if answers is not None else load_answers()
    if not isinstance(data, dict):
        return None

    terms: list[str] = []
    seen_terms: set[str] = set()
    for field in ("cargos", "palavras_chave_sorteio", "competencias_busca"):
        raw = data.get(field) or []
        if isinstance(raw, str):
            raw = [raw]
        for item in raw:
            term = str(item).strip()
            if term and term.lower() not in seen_terms:
                seen_terms.add(term.lower())
                terms.append(term)
            if len(terms) >= 4:
                break
        if len(terms) >= 4:
            break

    if not terms:
        return None

    modelos = {str(m).strip().lower() for m in (data.get("modelo") or [])}
    want_remote = not modelos or "remoto" in modelos
    want_onsite = "hibrido" in modelos or "presencial" in modelos
    cidade = str(data.get("cidade") or "").strip()
    uf_match = re.search(r"(?:-|/|,\s*)\s*([A-Za-z]{2})\b", cidade)
    uf = uf_match.group(1).upper() if uf_match else ""

    lines = [
        "# Buscas locais geradas pelo Meu Perfil (fora do git)",
        "",
        "## Categorias de busca",
        "",
        "### Prioridade 1: Buscas principais do perfil",
        "",
        "```",
    ]
    for term in terms:
        safe = term.replace('"', "")
        if want_remote:
            lines.append(f'gupy-search: -q "{safe}" --remote')
            lines.append(f'solides-search: -q "{safe}" --remote')
        if want_onsite and uf:
            lines.append(f'gupy-search: -q "{safe}" --state {uf}')
        lines.append(f'linkedin-search: -q "{safe}" -l "Brasil"')
        lines.append(f'freehire-search: -q "{safe}" --country BR')
    lines.extend(["```", ""])

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def profile_text(path: Path | None = None) -> str | None:
    if path is not None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    for cand in (local_profile_path(), _effective_profile_md()):
        text = _read_if_customized(cand)
        if text is not None:
            return text

    report = _cached_ai_perfil_report()
    if report:
        return report

    formatted = format_answers(load_answers()).strip()
    if formatted:
        return "# Resumo do perfil salvo na interface\n\n" + formatted
    return None


def profile_ready(claude_md: Path | None = None) -> bool:
    """True quando o perfil está configurado (via UI local em backend/documents/perfil ou /setup)."""
    if claude_md is not None:
        try:
            return "[YOUR_NAME]" not in claude_md.read_text(encoding="utf-8")
        except OSError:
            return False

    for cand in (_effective_claude_md(), local_profile_path(), _effective_profile_md()):
        if _read_if_customized(cand) is not None:
            return True

    if _cached_ai_perfil_report():
        return True

    answers = load_answers()
    if answers and (_has_uploaded_documents() or bool(answers.get("cargos"))):
        return True
    return False


# ---------------------------------------------------------------------------
# Áreas do Currículo (.md) para o Randomizador de Busca
# ---------------------------------------------------------------------------

def _clean_area_keyword(raw: object) -> str:
    ck = re.sub(r"^(?:avan[çc]ado|intermedi[áa]rio|b[áa]sico)\s*:\s*", "", str(raw), flags=re.IGNORECASE)
    ck = re.sub(r"[\(\)\[\]\*]", "", ck).strip(" ,;:-").rstrip(".")
    return ck


def _build_cv_areas(
    profile_md: Path | None = None,
    claude_md: Path | None = None,
    answers_path: Path | None = None,
) -> tuple[list[dict], str]:
    """Extrai palavras/eixos do campo editável no Meu perfil (prioritário) ou fallback do CV (.md)."""
    explicit_md = profile_md is not None or claude_md is not None

    raw_answers: dict = {}
    resolved_answers = answers_path if answers_path is not None else ANSWERS
    try:
        if resolved_answers and resolved_answers.exists():
            parsed_ans = json.loads(resolved_answers.read_text(encoding="utf-8"))
            if isinstance(parsed_ans, dict):
                raw_answers = parsed_ans
    except Exception:
        pass
    answers = clean_answers(raw_answers)

    areas: list[dict] = []
    seen_labels: set[str] = set()
    seen_kw_tuples: set[tuple] = set()

    def add_area(area_id: str, label: str, kws: list):
        clean_kws = []
        for k in kws:
            ck = _clean_area_keyword(k)
            if (
                ck
                and len(ck) >= 2
                and not ck.isdigit()
                and ck.lower() not in [x.lower() for x in clean_kws]
            ):
                clean_kws.append(ck)
        # Regra de ouro: no máximo 3 palavras-chave por área
        clean_kws = clean_kws[:3]
        if not clean_kws:
            return
        kw_key = tuple(x.lower() for x in clean_kws)
        if kw_key in seen_kw_tuples or label.lower() in seen_labels:
            return
        seen_kw_tuples.add(kw_key)
        seen_labels.add(label.lower())
        areas.append({
            "id": area_id,
            "label": label,
            "keywords": clean_kws,
        })

    # Prioridade absoluta: quando não há .md explícito e o campo editável do perfil
    # (`palavras_chave_sorteio`) tem palavras cadastradas (ou migradas), o sorteio
    # puxa exclusivamente dessa lista — 1 palavra por entrada para rotação uniforme.
    sort_keywords = answers.get("palavras_chave_sorteio") or []
    if not explicit_md and sort_keywords:
        for idx, kw in enumerate(sort_keywords, start=1):
            add_area(f"perfil-kw-{idx}", kw, [kw])
        if areas:
            return areas, "profile"

    # Fallback: carrega Markdowns locais/templates (ou caminhos explícitos em testes)
    chunks = []
    if explicit_md:
        for p in (profile_md, claude_md):
            try:
                if p and p.exists():
                    chunks.append(p.read_text(encoding="utf-8"))
            except OSError:
                pass
    else:
        for cand in (local_profile_path(), _effective_profile_md(), _effective_claude_md()):
            text = _read_if_customized(cand)
            if text:
                chunks.append(text)
        report = _cached_ai_perfil_report()
        if report:
            chunks.append(report)
    raw_md = "\n".join(chunks)

    # 1. Fallback de formulário quando palavras_chave_sorteio ainda está vazio
    cargos = answers.get("cargos") or []
    comp_busca = sort_keywords

    for idx, cargo in enumerate(cargos):
        matched_kws = [k for k in comp_busca if k.lower() in cargo.lower()]
        if not matched_kws:
            matched_kws = [cargo.split()[0]] + comp_busca[:2]
        slug = f"cargo-{idx+1}"
        add_area(slug, cargo, matched_kws)

    for i in range(0, len(comp_busca), 2):
        pair = comp_busca[i:i+2]
        if len(pair) == 2:
            add_area(f"comp-{i+1}", f"{pair[0]} & {pair[1]}", pair)
        elif len(pair) == 1:
            add_area(f"comp-{i+1}", pair[0], pair)

    # 2. Extrai tópicos explícitos de competências e cargos do markdown: "- **Categoria**: item1, item2, item3"
    current_section = ""
    for line in raw_md.splitlines():
        if line.startswith("#"):
            current_section = line.strip("# ").strip().lower()
            continue
        if any(skip in current_section for skip in (
            "projeto", "checklist", "deal-breakers", "filtro", "estrutura", "fluxo",
            "privacidade", "identidade", "documento", "diretriz", "publica", "premio",
            "referencia", "formação", "formacao", "experiência", "experiencia",
            "certifica", "comportamental", "motiva", "setores",
        )):
            continue
        m = re.match(r"^\s*-\s*\*\*([^*:]{2,55})(?:\*\*:\s*|:\*\*\s*)(.+)$", line)
        if not m:
            continue
        cat_label = m.group(1).strip()
        cat_low = cat_label.lower()
        if any(skip in cat_low for skip in (
            "nome", "local", "telefone", "e-mail", "linkedin", "github", "situação",
            "restrições", "gênero", "cnpj", "razão", "cnae", "endereço", "comprovante",
            "idioma", "cv language", "senioridade", "título", "pessoa jurídica",
            "foco", "orientação", "pontos", "rende", "português", "inglês", "espanhol", "deal",
        )):
            continue
        raw_items = [
            re.sub(r"^(?:avan[çc]ado|intermedi[áa]rio|b[áa]sico)\s*:\s*", "", re.sub(r"\([^)]*\)", "", x), flags=re.IGNORECASE).strip(" .;:")
            for x in re.split(r"[,;/]", m.group(2))
        ]
        items = [x for x in raw_items if 2 <= len(x) <= 35 and not x.endswith(")") and not x.isdigit()]

        # Subtermos da própria categoria (ex: Java, Python, TypeScript)
        cat_terms = [
            w for w in re.split(r"[/, &]+", cat_label)
            if len(w) >= 3 and w.lower() not in (
                "outros", "gerais", "principais", "secundarias", "secundárias",
                "dominio", "domínio", "softwares", "ferramentas", "bancos", "cache",
                "infra", "devops", "frameworks", "bibliotecas",
            )
        ]

        kws = []
        for term in (cat_terms + items):
            t_clean = term.strip("()[] ")
            if t_clean and not t_clean.isdigit() and t_clean.lower() not in [k.lower() for k in kws]:
                kws.append(t_clean)

        if kws:
            base_slug = re.sub(r"[^a-z0-9]+", "-", cat_low).strip("-") or f"area-{len(areas)+1}"
            for chunk_idx in range(0, len(kws), 3):
                chunk = kws[chunk_idx:chunk_idx + 3]
                if not chunk:
                    continue
                if chunk_idx == 0:
                    lbl = cat_label
                    slug = base_slug
                else:
                    lbl = f"{cat_label}: {' / '.join(chunk[:2])}"
                    slug = f"{base_slug}-{chunk_idx // 3 + 1}"
                add_area(slug, lbl, chunk)

    if not areas:
        areas.append({
            "id": "perfil-geral",
            "label": "Oportunidades do Perfil",
            "keywords": ["Vagas", "Oportunidades"],
        })

    return areas, "fallback"


def extract_cv_areas(
    profile_md: Path | None = None,
    claude_md: Path | None = None,
    answers_path: Path | None = None,
) -> list[dict]:
    """Retorna a lista de áreas/palavras-chave do CV usada no sorteio de busca."""
    areas, _ = _build_cv_areas(
        profile_md=profile_md,
        claude_md=claude_md,
        answers_path=answers_path,
    )
    return areas


def get_cv_areas_payload(
    profile_md: Path | None = None,
    claude_md: Path | None = None,
    answers_path: Path | None = None,
) -> dict:
    """Retorna `{areas, source}` indicando se as palavras vieram de `Meu perfil` ou do fallback."""
    areas, source = _build_cv_areas(
        profile_md=profile_md,
        claude_md=claude_md,
        answers_path=answers_path,
    )
    return {"areas": areas, "source": source}
