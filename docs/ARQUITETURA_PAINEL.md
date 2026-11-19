# Arquitetura do Painel Web Local (Vagamundo v2)

## 1. Princípios Arquiteturais

O painel de controle do **Vagamundo** opera como uma aplicação local *fullstack* desacoplada, projetada para rodar integralmente na máquina da pessoa candidata em modo *whitelabel*:

1. **Frontend SPA (`frontend/` — Angular + TypeScript):**
   - Construído com componentes *standalone*, **Angular Signals** e serviços globais de estado (`SearchStateService`, `RecruiterStateService`, `AutoModeService`, `ThemeService`) e componentes compartilhados (`CvRandomControlComponent`).
   - Comunica-se com o backend por meio de `ApiService` (`frontend/src/app/core/services/api.service.ts`) e proxy de desenvolvimento (`proxy.conf.json`) apontando para `http://127.0.0.1:8765`.
   - Visualização interativa em modo escuro/claro, barra global de status autônomo (`AutoModeBannerComponent`) e mapas SVG puros em DOM sem bibliotecas cartográficas externas.
2. **Backend API Gateway (`backend/api/` — FastAPI + Uvicorn):**
   - Servidor ASGI organizado sob `backend/api/` (`app.py`, `security.py`, `models.py`, `deps.py` e 9 módulos em `routes/`).
   - Documentação interativa OpenAPI gerada automaticamente em `http://127.0.0.1:8765/docs`.
   - Em produção local (ou quando `frontend/dist/frontend/browser` existe), o `app.py` serve diretamente os artefatos estáticos da SPA via `serve_spa` com proteção contra *path traversal*.
3. **Núcleo de Domínio (`backend/core/` e `backend/tools/`):**
   - Orquestra coleta em múltiplos portais (`scanner.py`, `scrape_run.py`), avaliação e geração por IA (`evaluator.py`, `docgen.py`, `ai_mux.py`, `backend/tools/ia/` com fachada `painel_ia.py`), verificação de URLs ativas (`liveness.py`), Radar de Recrutadores modular (`backend/core/recruiters/` — `service.py`, `collectors.py`, `parser.py`, `triage.py`, `search_terms.py`, com fachada `recruiter_service.py`) e Modo Automático Contínuo (`auto_mode.py`).
   - Armazena documentos locais em pastas ignoradas pelo Git: `backend/documents/cv/` (currículos enviados em PDF), `backend/documents/linkedin/` (exportações do perfil do LinkedIn em PDF) e `backend/documents/perfil/` (artefatos gerados `candidate-profile.md`, `search-queries.md` e `respostas.json`).
4. **Camada de Persistência Primária (`backend/db/` — SQLite WAL):**
   - Banco relacional local em `data/vagamundo.db` (`DEFAULT_DB_PATH` em `backend/db/__init__.py`) com modo *Write-Ahead Logging* (`WAL`), `PRAGMA foreign_keys = ON` e inicialização declarativa a partir de `backend/db/schema.sql`.
   - Estrutura modular em `backend/db/`: `repository.py` (fachada principal), `jobs_repo.py`, `applications_repo.py`, `recruiters_repo.py`, `analytics_repo.py`, `migrations.py` e `utils.py`.
5. **Gateway de IA Dual-Path (CLI + API Direta):**
   - Coexistem fluxos interativos por agentes de terminal (`.claude/skills/` e `.agents/skills/`) e operações diretas pela interface web via `ai_mux.py` / `ai_providers.py` (Google Gemini, Anthropic Claude, OpenAI e provedores compatíveis locais como Ollama). Veja [ADR 003](adr/003-dual-ai-path.md).

### Árvore Modular do Backend (`backend/`)

```
backend/
├── api/
│   ├── app.py                   # Aplicação FastAPI, middlewares e serve_spa
│   ├── deps.py                  # Injeção de dependências dos serviços
│   ├── models.py                # Schemas Pydantic de requisição/resposta
│   ├── security.py              # HostCheckMiddleware e verify_csrf_token
│   └── routes/                  # 9 módulos de rotas REST (/api/*)
│       ├── search.py
│       ├── jobs.py
│       ├── applications.py
│       ├── documents.py
│       ├── profile.py
│       ├── dashboard.py
│       ├── settings.py
│       ├── recruiters.py
│       └── auto_mode.py
├── core/
│   ├── recruiters/              # Pacote modular do Radar de Recrutadores
│   │   ├── service.py           # RecruiterService (orquestração, colagem e ações)
│   │   ├── collectors.py        # Coletores públicos (HN, GitHub, Remotive, 9 CLIs ao vivo, banco local)
│   │   ├── parser.py            # Higienização de e-mails, contexto e Snowflake ID do LinkedIn
│   │   ├── triage.py            # Triagem IA e promoção para Me Interessam / Descartadas
│   │   └── search_terms.py      # Expansão bilíngue PT↔EN via IA com cache
│   ├── recruiter_service.py     # Fachada retrocompatível para backend.core.recruiters
│   ├── auto_mode.py             # Loop autônomo contínuo anti-ban (Vagas e Recrutadores)
│   ├── scanner.py               # Execução assíncrona dos 24 portais e SSE
│   ├── evaluator.py             # Avaliação de aderência e triagem em lote
│   ├── tracker.py               # Gestão de vagas, decisões, candidaturas e linha do tempo
│   ├── docgen.py                # Geração de currículos LaTeX, cartas e dossiês de entrevista
│   ├── profile.py               # Formulário, upload de PDFs (.pdf) e organização por IA
│   ├── liveness.py              # Verificação anti-SSRF/TLS de vagas ativas vs encerradas
│   ├── ai_mux.py                # Multiplexador de provedores de IA
│   └── constants.py             # Constantes de domínio e limites compartilhados
├── db/
│   ├── repository.py            # Fachada unificada Repository
│   ├── jobs_repo.py             # Persistência e filtros de vagas e avaliações
│   ├── applications_repo.py     # Candidaturas, eventos e application_ledger
│   ├── recruiters_repo.py       # Publicações do radar e deduplicação
│   ├── analytics_repo.py        # Estatísticas de funil e dashboard
│   ├── migrations.py            # Migrações automáticas de schema SQLite
│   ├── utils.py                 # Helpers transacionais e serialização
│   └── schema.sql               # DDL declarativo das 9 tabelas
├── documents/
│   ├── cv/                      # Uploads de Currículo em PDF (.pdf)
│   ├── linkedin/                # Uploads de Perfil do LinkedIn em PDF (.pdf)
│   └── perfil/                  # Artefatos locais gerados (candidate-profile.md, search-queries.md, respostas.json)
└── tools/                       # Utilitários CLI, scrape_run.py, compile_doc.py, check_privacy.py e pacote ia/
```

---

## 2. Estrutura de Rotas da Interface (10 Páginas)

Definidas em `frontend/src/app/app.routes.ts` e expostas na barra lateral (`app.component.ts` / `sidebar.component.html`):

| Rota | Título no Menu | Responsabilidade Principal |
| :--- | :--- | :--- |
| `/dashboard` | **Dashboard** | Visão consolidada de métricas do funil, status de fontes, histórico recente e atalhos operacionais. |
| `/buscar-vagas` | **Buscar e Vagas** | Console com filtro por termo + sorteador do CV, seletor de **24 portais**, modelo de trabalho, região, `jobage`, nota IA, ordenação, alternância **Cards / Mapa SVG** (`GeoMapComponent`) e **Modo Automático**. |
| `/me-interessam` | **Vagas que Me Interessam** | Hub das vagas favoritadas manualmente ou promovidas pelo Modo Automático; geração de currículo adaptado, carta de apresentação, dossiê de entrevista e registro de candidatura. |
| `/recrutadores` | **Recrutadores** | Mineração de oportunidades com e-mail direto (`@`), Barra de Pesquisa LinkedIn (`LinkedinSearchBarComponent`) com avaliação inline por IA, prevenção de recontato via histórico imutável e Modo Automático Contínuo dedicado. |
| `/candidaturas` | **Minhas Candidaturas** | Gestão de pipeline (`aplicada`, `em_processo`, `entrevista`, `aprovada`, `rejeitada`), linha do tempo (`application_events`) e registro histórico (`application_ledger`). |
| `/evolucao` | **Evolução e Métricas** | Análise de lacunas de competências em relação às vagas avaliadas e plano de estudo (*upskilling*). |
| `/curriculos-cartas` | **Currículos e Cartas Compilados** | Histórico e visualização/download de PDFs e fontes `.tex` gerados em `backend/cv/` e `backend/cover_letters/`. |
| `/descartadas` | **Vagas Descartadas** | Repositório com busca, restauração em 1 clique para **Me Interessam** e exclusão definitiva do banco de dados. |
| `/meu-perfil` | **Meu Perfil** | Formulário minimalista de perfil e busca (incluindo `palavras_chave_sorteio`), upload estrito de arquivos **`.pdf`** (Currículo em `backend/documents/cv/` e LinkedIn em `backend/documents/linkedin/`) e botões **"Organizar tudo do PDF com a IA"** e **"Montar meu perfil com a IA"** (gravando em `backend/documents/perfil/`). |
| `/configuracoes` | **Configurações do Assistente de IA** | Seleção de provedor de IA ativo, gerenciamento seguro de chaves no `.env` da raiz e teste de conectividade. |

---

## 3. Catálogo de Portais e Fontes de Coleta (24 CLIs + Feeds Abertos)

Os 24 coletores em formato portátil **Agent Skills** (`.agents/skills/*/cli/src/cli.ts`, executados via **Bun**) ficam catalogados em `AVAILABLE_PORTALS` (`frontend/src/app/core/utils/job-filters.util.ts`):

- **Portais Brasil (8):** `gupy-search`, `solides-search`, `vagas-search`, `infojobs-search`, `empregos-search`, `trampos-search`, `digai-search`, `pcd-search`.
- **Tecnologia & Inovação (5):** `geekhunter-search`, `programathor-search`, `remotar-search`, `greenhouse-search`, `ashby-search`.
- **Internacional & Remoto Global (7):** `remoteok-search`, `jobicy-search`, `hn-search`, `freehire-search`, `linkedin-search`, `hh-search`, `habrcareer-search`.
- **Executivo & Especialistas (2):** `michaelpage-search`, `roberthalf-search`.
- **Agronegócio (2):** `agrobase-search`, `agrosearch-search`.

Complementarmente, o Radar de Recrutadores (`backend/core/recruiters/collectors.py`) integra feeds abertos nativos em Python: **HN Algolia Who is Hiring**, **GitHub Vagas BR (Issues)**, **Remotive API** e varredura paralela ao vivo nos 9 portais com descrição completa (`RECRUITER_LIVE_PORTALS`).

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
| `search.py` | `GET /api/status`, `POST /api/search`, `POST /api/search/cancel`, `GET /api/search/stream` (`GET /api/stream`), `POST /api/clear-pending`, `GET /api/health`. |
| `jobs.py` | `GET /api/vagas` (`GET /api/results`, `GET /api/saved`, `GET /api/discarded`), `GET /api/jobs`, `GET /api/jobs/{job_id}`, `POST /api/evaluate` (`POST /api/batch-screen`, `POST /api/saved/batch-reevaluate`, `GET /api/saved/batch-status`), `POST /api/prepare` (`POST /api/mark`), `POST /api/discard` (`POST /api/saved/batch-discard`, `POST /api/discarded/delete`, `POST /api/discarded/clear`), `POST /api/restore`, `POST /api/clear-pending`, `POST /api/jobs/check-liveness` (`POST /api/jobs/liveness`). |
| `applications.py` | `GET /api/applications`, `POST /api/applications`, `POST /api/apply` (`POST /api/applied`, `POST /api/applied/batch`), `POST /api/outcome` (`GET /api/applications/{app_id}/events`, `POST /api/applications/event`, `DELETE /api/applications/event/{event_id}`, `POST /api/applications/remove`), `POST /api/reopen` (`POST /api/applications/reopen-recruiter`). |
| `documents.py` | `GET /api/documents`, `GET /api/cv-areas`, `GET /api/documents/download` (`GET /api/file`), `POST /api/documents/delete` (`POST /api/documents/clear`), `POST /api/claude`, `POST /api/compile`. |
| `profile.py` | `GET /api/profile`, `POST /api/profile/answers` (`POST /api/profile`, `POST /api/profile/organize`), `POST /api/profile/upload` (`POST /api/upload`), `POST /api/profile/delete-file` (`POST /api/upload-remove`), `POST /api/profile/reset`, `GET /api/evolution` (`GET /api/evolucao`), `POST /api/evolution/check` (`POST /api/evolucao/atualizar`), `GET /api/geo`. |
| `dashboard.py` | `GET /api/dashboard` (`GET /api/dashboard/stats`), `GET /api/analytics`, `GET /api/geo`. |
| `settings.py` | `GET /api/token`, `GET /api/settings`, `POST /api/settings`, `POST /api/settings/test`. |
| `recruiters.py` | `GET /api/recruiters`, `GET /api/recruiters/keywords`, `GET /api/recruiters/cv-areas`, `POST /api/recruiters/expand-search-term`, `POST /api/recruiters/sync`, `POST /api/recruiters/triage`, `POST /api/recruiters/save-job` (`POST /api/recruiters/{post_id}/interested`), `POST /api/recruiters/paste`, `POST /api/recruiters/paste-batch`, `POST /api/recruiters/outreach`, `POST /api/recruiters/mark-sent` (`POST /api/recruiters/{post_id}/contacted`), `POST /api/recruiters/dismiss` (`DELETE /api/recruiters/{post_id}`, `POST /api/recruiters/dismiss-batch`), `POST /api/recruiters/clear`, `GET/POST /api/recruiters/auto/config`, `POST /api/recruiters/auto/start`. |
| `auto_mode.py` | `GET /api/auto-mode/status`, `GET/POST /api/auto-mode/config`, `POST /api/auto-mode/start`, `POST /api/auto-mode/stop` (`POST /api/auto-mode/cancel`), `GET /api/auto-mode/stream`, `POST /api/auto-mode/skip-cooldown`, `POST /api/auto-mode/undo`, `POST /api/auto-mode/undo-job`. |

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
