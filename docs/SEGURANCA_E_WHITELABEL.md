# Segurança, Whitelabel e Privacidade Pré-Push

Este documento descreve todas as barreiras de proteção de dados pessoais (**whitelabel**), endurecimento (*hardening*) da aplicação web e controles de segurança sobre as skills e automações do **Vagamundo**.

---

## 1. Arquitetura Whitelabel e Privacidade Pré-Push

O repositório é estruturado para ser clonado e usado por qualquer colega **sem expor dados pessoais, chaves de API ou preferências hardcoded** no histórico Git:

1. **Arquivos pessoais desacoplados via `skip-worktree`:**
   - [CLAUDE.md](../CLAUDE.md), `.claude/skills/job-application-assistant/01-candidate-profile.md` e `.claude/skills/job-scraper/search-queries.md` permanecem limpos com placeholders no `HEAD`. Após personalizar com `/setup`, o fluxo marca `git update-index --skip-worktree` para impedir commits acidentais.
2. **Regras estritas de `.gitignore`:**
   - Bloqueiam `.env`, `backend/.env` (com regras `deny` no `.claude/settings.json` para `Read(.env)` e `Read(backend/.env)`), banco `data/vagamundo.db`, perfil isolado do navegador do LinkedIn (`data/browser_profile/`), planilhas pessoais (`job_search_tracker.csv`), arquivos sob `backend/documents/*` (exceto `.gitkeep` e `README.md`) e PDFs/TeX compilados sob `backend/cv/` e `backend/cover_letters/` (mantendo apenas os modelos `*_example.*`).
3. **Auditoria automatizada (`backend/tools/check_privacy.py`):**
   - Verifica segredos (chaves API, tokens, CPF/CNPJ formatados), dados do perfil local carregados em memória sem vazar os valores nos logs e integridade do `.gitignore` / `skip-worktree`.
4. **Código e Testes agnósticos ao candidato:**
   - Os coletores e avaliadores (`backend/tools/eures.py`, `backend/tools/google_careers.py`, `backend/tools/painel_ia.py`) extraem áreas dinamicamente do perfil configurado em `painel_perfil.py`, sem termos ou instituições pessoais fixos em código ou suítes de teste (`backend/tests/`).

---

## 2. Segurança do Backend API e Coletores

1. **Validação estrita de cabeçalho `Host` (`backend/api/security.py` — `HostCheckMiddleware`):**
   - Rejeita cabeçalhos `Host` vazios e extrai o hostname tratando corretamente brackets IPv6 (`[::1]:8765` -> `::1`), validando igualdade exata contra `ALLOWED_HOSTS` (`localhost`, `127.0.0.1`, `::1`, `testserver`).
   - Impede ataques de *DNS rebinding* e spoofing de subdomínio (ex.: `localhost.attacker.com`).
2. **Proteção CSRF por token de sessão (`verify_csrf_token`):**
   - Todas as rotas mutáveis (`POST`, `DELETE`) exigem o token `SESSION_TOKEN` obtido no bootstrap local (`/api/token`).
3. **Contenção de *Path Traversal* na SPA (`backend/api/app.py` — `serve_spa`):**
   - Resolve o caminho solicitado com `.resolve()` e valida explicitamente `file_path.is_relative_to(dist_root)` antes de entregar arquivos estáticos.
4. **Proteção Anti-SSRF e TLS Estável (`backend/core/liveness.py`, `backend/tools/eures.py`):**
   - `validate_public_http_url(url)` em `liveness.py` bloqueia esquemas não-HTTP(S) (`file://`, `ftp://`, `javascript:`), hostnames locais/internos (`localhost`, `*.local`, `*.internal`, `metadata.google.internal`) e endereços IP privados, de loopback, *link-local* ou reservados antes de disparar sondagens assíncronas (`verify=True`).
   - O conector EURES utiliza exclusivamente `ssl.create_default_context()` com verificação de certificado TLS ativa.
5. **Compilação LaTeX Segura (`backend/tools/compile_doc.py`):**
   - Executa `pdflatex` em lista de argumentos explícita (sem `shell=True` nem `--shell-escape`) e com validação de diretório destino.

---

## 3. Segurança no Frontend (XSS / CSP)

- As visualizações SVG interativas em `BuscarVagasComponent` (`renderWorldMapSvg`, `renderBrasilMapSvg`, `createSvgEl`, `appendOceanGradient`, `createMapBadge`) constroem todo o DOM vetorial via `document.createElementNS` + `.replaceChildren()` + `.textContent`, sem qualquer uso de `innerHTML`, `outerHTML` ou `eval`.
- Os templates Angular e renderizações locais evitam injeção direta de HTML não sanitizado, enquanto `backend/tools/security_guards.py` audita permissões, regras do `.gitignore`, manifestos JS/TS e ferramentas de skills/agentes.

---

## 4. Governança de Skills, Guards e SkillSpector

- **Allowlist sincronizada:** Todos os **24 portais CLI** em `.agents/skills/` possuem entradas correspondentes em `.claude/settings.json` e `ALLOWED_PERMISSIONS` em `backend/tools/security_guards.py`, validado automaticamente pela suíte `backend/tests/test_security_guards.py`. (A antiga checagem das permissões desassistidas de `backend/tools/painel/claude-settings*.json` foi aposentada junto com a remoção do servidor HTTP legado.)
- **Pipeline de CI (`.github/workflows/ci.yml`):** Aponta para os caminhos reais (`backend/tools/*`, `backend/tests`, `backend/cv`, `backend/cover_letters`) nos branches `main` e `master`.
- **Auditoria NVIDIA SkillSpector:**
  - `.claude/skills/` é verificada para garantir ausência de referências quebradas ou escalação indevida de ferramentas.
  - `.agents/skills/` apresenta apenas achados estáticos esperados de pacote CLI Node/Bun (`SC1` versões com `^`/`~` em `cli/package.json` e `LP1` acesso de rede/variáveis de ambiente nos executores CLI e testes vivos), sem indícios maliciosos. Execute a auditoria com o diretório limpo de dependências instaladas (`cli/node_modules`, gitignored) — ou excluindo `node_modules` — para evitar falsos alertas `CRITICAL` (`SC9`) em pacotes de terceiros após `bun install`. (Rodar `bun run typecheck` localmente exige ter feito `bun install` antes.)
