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
ANSWERS = DOCUMENTS / "perfil" / "respostas.json"
PROFILE_MD = REPO_ROOT / ".claude" / "skills" / "job-application-assistant" / "01-candidate-profile.md"
UPLOAD_KINDS = {"cv": "cv", "linkedin": "linkedin"}
MAX_UPLOAD = 10_000_000

LEVELS = list(_posting_signals.LEVELS)

# Seções do formulário: (título, campos). Tipos: text, textarea, lines (uma
# entrada por linha, gravada como lista), choice (uma opção), multi (várias).
SCHEMA = [
    ("Quem é você", [
        {"key": "cidade", "label": "Cidade e UF", "type": "text", "placeholder": "Campinas - SP"},
        {"key": "genero", "label": "Nos textos em português, escrever no", "type": "choice",
         "options": ["feminino", "masculino", "neutro"],
         "help": "Feminino: \"formada\"; masculino: \"formado\"; neutro: \"tenho formação em\"."},
        {"key": "idiomas", "label": "Idiomas e nível, um por linha", "type": "lines",
         "placeholder": "Português - nativo\nInglês - avançado",
         "help": "Seja realista: uma vaga que exige um idioma fora desta lista é descartada."},
        {"key": "situacao", "label": "Situação atual", "type": "text",
         "placeholder": "Empregada CLT, buscando a próxima posição"},
    ]),
    ("O trabalho que você busca", [
        {"key": "cargos", "label": "Cargos a buscar, um por linha", "type": "lines",
         "placeholder": "Product Manager\nProduct Owner"},
        {"key": "senioridade", "label": "Níveis que fazem sentido", "type": "multi", "options": LEVELS},
        {"key": "setores", "label": "Setores de interesse, um por linha", "type": "lines"},
        {"key": "competencias_busca", "label": "Competências que aparecem nas vagas, uma por linha", "type": "lines"},
        {"key": "empresas", "label": "Empresas que você quer acompanhar (opcional)", "type": "lines"},
        {"key": "motivacao", "label": "O que te motiva no trabalho", "type": "textarea"},
    ]),
    ("Condições", [
        {"key": "modelo", "label": "Modelo de trabalho aceito", "type": "multi", "options": ["remoto", "hibrido", "presencial"]},
        {"key": "locais", "label": "Cidades aceitas para híbrido ou presencial", "type": "text"},
        {"key": "regimes", "label": "Regimes aceitos", "type": "multi",
         "options": ["CLT", "PJ", "estagio", "temporario", "freelance"]},
        {"key": "pretensao_clt", "label": "Pretensão em CLT (bruto mensal)", "type": "text", "placeholder": "R$ 8 a 10 mil"},
        {"key": "pretensao_pj", "label": "Mínimo em PJ, se aceitar", "type": "text"},
        {"key": "deal_breakers", "label": "O que você não aceita de jeito nenhum", "type": "textarea"},
    ]),
    ("Opcional", [
        {"key": "idioma_cv", "label": "Idioma do currículo", "type": "choice", "options": ["português", "inglês"]},
        {"key": "comportamental", "label": "Perfil comportamental (resultado de PI, DISC, Gupy... ou como você trabalha melhor)",
         "type": "textarea"},
    ]),
]
FIELDS = {f["key"]: f for _, fields in SCHEMA for f in fields}


# ---------------------------------------------------------------------------
# Formulário
# ---------------------------------------------------------------------------

def clean_answers(data: dict) -> dict:
    """Só os campos do formulário, nos tipos certos; o resto é descartado."""
    out = {}
    for key, field in FIELDS.items():
        value = data.get(key)
        kind = field["type"]
        if kind in ("text", "textarea", "choice") and isinstance(value, str):
            value = value.strip()[:4000]
            if kind == "choice" and value not in field["options"]:
                continue
            if value:
                out[key] = value
        elif kind in ("lines", "multi"):
            items = value.splitlines() if isinstance(value, str) else value if isinstance(value, list) else []
            items = [i.strip()[:200] for i in items if isinstance(i, str) and i.strip()][:30]
            if kind == "multi":
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


def save_upload(kind: str, name: str, data_b64: str, base: Path = DOCUMENTS) -> str:
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


def list_uploads(base: Path = DOCUMENTS) -> dict:
    out = {}
    for kind, sub in UPLOAD_KINDS.items():
        folder = base / sub
        files = sorted(p for p in folder.glob("*") if p.is_file() and p.name != ".gitkeep") if folder.is_dir() else []
        out[kind] = [{"name": p.name, "size": p.stat().st_size,
                      "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes")} for p in files]
    return out


def remove_upload(kind: str, name: str, base: Path = DOCUMENTS) -> None:
    """Apaga só um arquivo que a listagem mostra, pelo nome exato."""
    if kind not in UPLOAD_KINDS or name not in {f["name"] for f in list_uploads(base)[kind]}:
        raise ValueError("arquivo não encontrado")
    (base / UPLOAD_KINDS[kind] / name).unlink()


def has_documents(base: Path = DOCUMENTS) -> bool:
    return any(list_uploads(base).values())


# ---------------------------------------------------------------------------
# Privacidade: para onde este repositório publica
# ---------------------------------------------------------------------------

def github_repo(url: str) -> str | None:
    """owner/repo de um remoto do GitHub (https ou ssh), ou None."""
    m = re.match(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def privacy(root: Path = REPO_ROOT) -> dict:
    """status: local (sem remoto), privado, outro (remoto fora do GitHub), publico ou desconhecido."""
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


def profile_text(path: Path = PROFILE_MD) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def profile_ready(claude_md: Path = REPO_ROOT / "CLAUDE.md") -> bool:
    """O /setup já rodou: o CLAUDE.md não tem mais o marcador do modelo."""
    try:
        return "[YOUR_NAME]" not in claude_md.read_text(encoding="utf-8")
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Áreas do Currículo (.md) para o Randomizador de Busca
# ---------------------------------------------------------------------------

def extract_cv_areas(
    profile_md: Path = PROFILE_MD,
    claude_md: Path = REPO_ROOT / "CLAUDE.md",
    answers_path: Path = ANSWERS,
) -> list[dict]:
    """Extrai áreas/eixos técnicos de qualquer currículo (.md) de forma 100% dinâmica (whitelabel)."""
    chunks = []
    for p in (profile_md, claude_md):
        try:
            if p and p.exists():
                chunks.append(p.read_text(encoding="utf-8"))
        except OSError:
            pass
    raw_md = "\n".join(chunks)

    areas: list[dict] = []
    seen_labels: set[str] = set()
    seen_kw_tuples: set[tuple] = set()

    def add_area(area_id: str, label: str, kws: list):
        clean_kws = []
        for k in kws:
            ck = re.sub(r"^(?:avan[çc]ado|intermedi[áa]rio|b[áa]sico)\s*:\s*", "", str(k), flags=re.IGNORECASE)
            ck = re.sub(r"[\(\)\[\]\*]", "", ck).strip(" ,.;:-")
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

    # 1. Extrai dos dados configurados no perfil (respostas.json / formulário local)
    answers = {}
    try:
        if answers_path and answers_path.exists():
            answers = json.loads(answers_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    cargos = answers.get("cargos") or []
    comp_busca = answers.get("competencias_busca") or []

    for idx, cargo in enumerate(cargos):
        matched_kws = [k for k in comp_busca if k.lower() in cargo.lower()]
        if not matched_kws:
            matched_kws = [cargo.split()[0]] + comp_busca[:2]
        slug = f"cargo-{idx+1}"
        add_area(slug, cargo, matched_kws)

    # Agrupamentos de competências da busca (em pares de 2)
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

    return areas
