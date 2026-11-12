# Arquitetura do Painel Web Local (Vagamundo v2)

## 1. Princípios Arquiteturais

O painel de controle do **Vagamundo** opera como uma aplicação local *fullstack* desacoplada, projetada para rodar integralmente na máquina da pessoa candidata em modo *whitelabel*:

1. **Frontend SPA (`frontend/` — Angular + TypeScript):**
   - Construído com componentes *standalone*, **Angular Signals** e serviços globais de estado (`SearchStateService`, `RecruiterStateService`, `AutoModeService`, `ThemeService`).
   - Comunica-se com o backend por meio de `ApiService` (`frontend/src/app/core/services/api.service.ts`) e proxy de desenvolvimento (`proxy.conf.json`) apontando para `http://127.0.0.1:8765`.
   - Visualização interativa em modo escuro/claro, barra global de status autônomo (`AutoModeBannerComponent`) e mapas SVG puros em DOM sem bibliotecas cartográficas externas.
2. **Backend API Gateway (`backend/api/` — FastAPI + Uvicorn):**
   - Servidor ASGI organizado sob `backend/api/` (`app.py`, `security.py`, `models.py`, `deps.py` e 9 módulos em `routes/`).
   - Documentação interativa OpenAPI gerada automaticamente em `http://127.0.0.1:8765/docs`.
   - Em produção local (ou quando `frontend/dist/frontend/browser` existe), o `app.py` serve diretamente os artefatos estáticos da SPA via `serve_spa` com proteção contra *path traversal*.
3. **Núcleo de Domínio (`backend/core/` e `backend/tools/`):**
   - Orquestra coleta em múltiplos portais (`scanner.py`, `scrape_run.py`), avaliação e geração por IA (`evaluator.py`, `docgen.py`, `ai_mux.py`, `painel_ia.py`), verificação de URLs ativas (`liveness.py`), Radar de Recrutadores (`recruiter_service.py`) e Modo Automático Contínuo (`auto_mode.py`).
4. **Camada de Persistência Primária (`backend/db/` — SQLite WAL):**
   - Banco relacional local em `data/vagamundo.db` (`DEFAULT_DB_PATH` em `backend/db/__init__.py`) com modo *Write-Ahead Logging* (`WAL`), `PRAGMA foreign_keys = ON` e inicialização declarativa a partir de `backend/db/schema.sql`.
5. **Gateway de IA Dual-Path (CLI + API Direta):**
   - Coexistem fluxos interativos por agentes de terminal (`.claude/skills/` e `.agents/skills/`) e operações diretas pela interface web via `ai_mux.py` / `ai_providers.py` (Google Gemini, Anthropic Claude, OpenAI e provedores compatíveis locais como Ollama). Veja [ADR 003](adr/003-dual-ai-path.md).

---

## 2. Estrutura de Rotas da Interface (10 Páginas)

Definidas em `frontend/src/app/app.routes.ts` e expostas na barra lateral (`app.component.ts` / `sidebar.component.html`):

| Rota | Título no Menu | Responsabilidade Principal |
| :--- | :--- | :--- |
| `/dashboard` | **Dashboard** | Visão consolidada de métricas do funil, status de fontes, histórico recente e atalhos operacionais. |
| `/buscar-vagas` | **Buscar e Vagas** | Console com filtro por termo + sorteador do CV, seletor de **24 portais**, modelo de trabalho, região, `jobage`, nota IA, ordenação, alternância **Cards / Mapa SVG** e **Modo Automático**. |
| `/me-interessam` | **Vagas que Me Interessam** | Hub das vagas favoritadas manualmente ou promovidas pelo Modo Automático; geração de currículo adaptado, carta de apresentação, dossiê de entrevista e registro de candidatura. |
| `/recrutadores` | **Recrutadores** | Mineração de oportunidades com e-mail direto (`@`), prevenção de recontato via histórico imutável, triagem IA calibrada e Modo Automático Contínuo dedicado. |
| `/candidaturas` | **Minhas Candidaturas** | Gestão de pipeline (`aplicada`, `em_processo`, `entrevista`, `aprovada`, `rejeitada`), linha do tempo (`application_events`) e registro histórico (`application_ledger`). |
| `/evolucao` | **Evolução e Métricas** | Análise de lacunas técnicas em relação às vagas avaliadas e plano de estudo (*upskilling*). |
| `/curriculos-cartas` | **Currículos e Cartas Compilados** | Histórico e visualização/download de PDFs e fontes `.tex` gerados em `backend/cv/` e `backend/cover_letters/`. |
| `/descartadas` | **Vagas Descartadas** | Repositório com busca e restauração em 1 clique para **Me Interessam** ou **Pendentes**. |
| `/meu-perfil` | **Meu Perfil** | Edição de dados e preferências whitelabel, upload e extração estruturada de currículo base (`.pdf`, `.docx`, `.txt`). |
| `/configuracoes` | **Configurações do Assistente de IA** | Seleção de provedor de IA ativo, gerenciamento seguro de chaves no `.env` local e teste de conectividade. |

---

## 3. Catálogo de Portais e Fontes de Coleta (24 CLIs + Feeds Abertos)

Os 24 coletores em formato portátil **Agent Skills** (`.agents/skills/*/cli/src/cli.ts`, executados via **Bun**) ficam catalogados em `AVAILABLE_PORTALS` (`frontend/src/app/core/utils/job-filters.util.ts`):

- **Portais Brasil (8):** `gupy-search`, `solides-search`, `vagas-search`, `infojobs-search`, `empregos-search`, `trampos-search`, `digai-search`, `pcd-search`.
- **Tecnologia & Inovação (5):** `geekhunter-search`, `programathor-search`, `remotar-search`, `greenhouse-search`, `ashby-search`.
- **Internacional & Remoto Global (7):** `remoteok-search`, `jobicy-search`, `hn-search`, `freehire-search`, `linkedin-search`, `hh-search`, `habrcareer-search`.
- **Executivo & Especialistas (2):** `michaelpage-search`, `roberthalf-search`.
- **Agronegócio (2):** `agrobase-search`, `agrosearch-search`.

Complementarmente, o backend integra conectores e feeds abertos nativos em Python: **EURES** (`eures.py`), **Google Careers** (`google_careers.py`), **HN Algolia Who is Hiring**, **GitHub Vagas BR (Issues)** e **Remotive API** (`recruiter_service.py`).

---

## 4. Schema SQLite (9 Tabelas)

Definido em `backend/db/schema.sql`:

1. `jobs` — Catálogo unificado de vagas (`url` única, título, empresa, localização, `work_model`, modalidade, descrição, status, metadados).
2. `applications` — Candidaturas vinculadas a `jobs`, estágio no funil, observações e timestamps.
3. `status_log` — Histórico de transições de status das vagas/candidaturas.
4. `evaluations` — Avaliações e notas geradas pela IA ou heurísticas para cada vaga.
5. `profile` — Armazenamento chave-valor do perfil parseado, preferências, histórico de palavras-chave sorteadas e configurações operacionais.
6. `scan_runs` — Registro de execuções de busca/scraping (`query`, escopo, contagens, resumo JSON).
7. `application_events` — Eventos cronológicos detalhados por candidatura (contato, entrevista, retorno).
8. `application_ledger` — Livro-razão imutável de candidaturas e e-mails contatados (`job_url`, `email`, empresa, contexto), garantindo rastreabilidade e alerta contra reenvio duplicado mesmo se uma vaga mudar de status.
9. `recruiter_posts` — Publicações mineradas com e-mails diretos, classificação (`vaga_ativa` vs `nao_e_vaga`), `ai_score`, `ai_verdict`, `ai_best_email` e vínculo ao histórico.

---

## 5. Visão Geral dos Routers REST (`/api/*`)

| Router (`backend/api/routes/`) | Principais Endpoints e Função |
| :--- | :--- |
| `settings.py` | `/api/health`, `/api/session` (emite token CSRF local), `/api/settings` (provedores/chaves de IA). |
| `search.py` | Disparos de busca multi-portal em background, consulta de progresso, leitura de resultados e estatísticas `/api/eures/stats` e `/api/geo`. |
| `jobs.py` | Listagem paginada/filtrada, `evaluate` (triagem rápida IA), `star`/`dismiss`/`restore`, verificação em lote `check-liveness` e leitura completa da vaga. |
| `applications.py` | CRUD de candidaturas, timeline (`application_events`), atualização de status e histórico (`application_ledger`). |
| `recruiters.py` | Busca/sincronização do Radar de Recrutadores, colagem manual (`paste`), marcação de contato enviado (`mark-contacted`), promoção para *Me Interessam*, descarte e reabertura. |
| `auto_mode.py` | Configuração (`GET/POST /api/auto-mode/config` e `recruiters/config`), início (`start`, `recruiters/start`), polling (`status`), `cancel`, `skip-cooldown` e reversão (`undo-run`, `undo-job`). |
| `documents.py` | Geração sob medida de currículo/carta/dossiê de entrevista e listagem/download de PDFs compilados. |
| `profile.py` | Leitura e salvamento de preferências do candidato + upload/parsing de CV para preenchimento automático de áreas-chave. |
| `dashboard.py` | Métricas agregadas, taxa de resposta, distribuição por status/fonte e recomendações de evolução. |

*(Todas as rotas de mutação `POST`/`DELETE` exigem o token `SESSION_TOKEN` validado por `verify_csrf_token` e cabeçalho `Host` autorizado por `HostCheckMiddleware`.)*

---

## 6. Inicialização Unificada e Auto-Restart (`dev.js`)

O script de desenvolvimento na raiz gerencia todo o ciclo local:

```bash
npm run dev
```

Em `dev.js`:
1. Limpa processos órfãos nas portas `8765` (backend) e `4200` (frontend) antes da subida.
2. Inicia o servidor FastAPI via Uvicorn (`127.0.0.1:8765`), aguardando `/api/health` ficar responsivo.
3. Monitora quedas inesperadas do processo backend durante a sessão, aplicando **auto-restart** com espera progressiva para evitar travamento silencioso da UI (como `ERR_CONNECTION_REFUSED`).
4. Inicia o servidor Angular (`ng serve`) na porta `4200` com `--proxy-config proxy.conf.json`.
