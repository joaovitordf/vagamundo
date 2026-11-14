# Relatório de Atualizações Não Documentadas e Auditoria Pré-Push

Este relatório consolida todas as alterações recentes implementadas no código após a atualização anterior da documentação (commit `984d4b4`, incluindo o commit `0172932` e as modificações atuais antes do push), os achados levantados na auditoria inicial (*SkillSpector*, código legado, hardcoding/whitelabel e inconsistências entre documentação e implementação) e as correções aplicadas após aprovação do plano.

---

## 1. Alterações Recentes Ainda Não Documentadas em `docs/`

### 1.1. Modularização da Camada de Inteligência Artificial (`backend/tools/ia/`)
No commit `0172932`, o módulo monolítico `backend/tools/painel_ia.py` foi refatorado em fachada de compatibilidade delegando para submódulos especializados:
- **`backend/tools/ia/_facade.py`**: resolução centralizada de dependências e acesso ao provedor ativo (`ai_providers`).
- **`backend/tools/ia/context.py`**: construção e compactação do contexto do candidato a partir de arquivos locais sob `backend/documents/` (`cv/`, `perfil/`), permitindo triagem e geração mesmo sem `01-candidate-profile.md` personalizado.
- **`backend/tools/ia/posting_reader.py`**: extração, limpeza e compactação do texto bruto de anúncios de vagas.
- **`backend/tools/ia/doc_builder.py`**: geração de avaliações detalhadas, currículos LaTeX, cartas de apresentação, dossiês de entrevista e extração estruturada do perfil via `extrair_respostas_de_documentos`.
- **`backend/tools/ia/triage.py`**: triagem em lote com calibração por âncoras (`Âncora A/B/C`), pesos canônicos (`30%` técnica, `25%` experiência/senioridade, `15%` comportamental, `30%` carreira), teto automático de nota (`45`) para senioridade incompatível, avaliação pela trilha de maior aderência em publicações multi-vaga e função `sortear_palavras_chave_busca`.

### 1.2. Radar de Recrutadores + Worker Isolado de LinkedIn (`backend/core/linkedin_browser.py`)
Entre o commit `0172932` e as mudanças no working tree, o Radar de Recrutadores recebeu integração direta e reorganização visual:
- **Sessão isolada de navegador (`backend/core/linkedin_browser.py`)**: usa perfil isolado em `data/browser_profile/` (ignorado pelo Git) com controle completo via API (`/api/recruiters/linkedin/status`, `/connect`, `/verify`, `/config`, `/disconnect`).
- **Modo `linkedin_only` no Modo Automático (`backend/core/auto_mode.py`, `backend/core/recruiter_service.py`)**: quando `linkedin_worker` está presente no serviço de recrutadores, o loop contínuo de recrutadores opera em modo `linkedin_only=True`, priorizando publicações `linkedin_post` e ignorando feeds públicos secundários na rodada automática.
- **Reabertura de candidaturas (`POST /api/applications/reopen-recruiter`)**: permite retornar uma vaga ao radar preservando rastreabilidade.
- **Interface em Duas Colunas (`frontend/src/app/features/recrutadores/`)**:
  - **Coluna esquerda (`Atuais encontrados`)**: resultados filtrados da busca/rodada corrente.
  - **Coluna direita (`Histórico de vagas relevantes`)**: acumula oportunidades `vaga_ativa` já avaliadas pela IA (`ai_evaluated_at`) entre mudanças de palavra-chave, persistidas em `RecruiterStateService` até descarte manual (`Limbo`).
  - **Ações em lote**: seleção múltipla, botão `Deletar nota < 45` e exclusão em lote via `POST /api/recruiters/dismiss-batch` (`RecruiterDismissBatchRequest`).
- **Deduplicação e visibilidade no SQLite (`backend/db/repository.py`)**: `find_recruiter_post_for_dedup` ganhou normalização `_norm_dedup_text` e comparação combinada de e-mail + título significativo + prefixo/descrição para evitar mesclar vagas diferentes publicadas pelo mesmo recrutador; `list_recruiter_posts` mantém visibilidade de posts sem vazar itens já aplicados/descartados.

### 1.3. Perfil Minimalista, Extração por IA e Unificação do Botão "Sortear área CV"
As alterações atuais no working tree unificaram a origem das palavras-chave usadas na busca manual e no Radar de Recrutadores:
- **Esquema minimalista em `backend/tools/painel_perfil.py` (`SCHEMA`)**: reduzido para **10 campos essenciais** distribuídos em `Perfil e busca` (`cidade`, `idiomas`, `cargos`, `palavras_chave_sorteio`, `senioridade`) e `Condições e regras` (`modelo`, `locais`, `regimes`, `deal_breakers`, `genero`). Campos redundantes anteriores (`situacao`, `setores`, `empresas_alvo`, `pretensao`, `linguagem_cv`) foram removidos e `competencias_busca` foi substituído por `palavras_chave_sorteio` (com migração transparente em `clean_answers` ao carregar arquivos `respostas.json` antigos).
- **Organização automática por documentos (`POST /api/profile/organize`)**: `ProfileService.organize_profile_from_documents` lê os PDFs locais enviados em `backend/documents/perfil/` (ou `cv/` e `linkedin/`), extrai os campos objetivos via IA (`extrair_respostas_de_documentos`), sincroniza `backend/documents/perfil/search-queries.md` (`sync_local_queries_from_answers`) e consolida o perfil sem editar arquivos versionados.
- **Controle compartilhado `Sortear área CV` (`CvRandomControlComponent`, `cv-area-picker.util.ts`, `GET /api/cv-areas`)**:
  - O endpoint `/api/cv-areas` retorna `{areas, source}` (`"profile"` quando `palavras_chave_sorteio` está preenchido, ou `"fallback"` quando extrai dos Markdowns/respostas).
  - Reutilizado tanto em `/buscar-vagas` (`SearchFiltersPanelComponent`) quanto em `/recrutadores` (`RecrutadoresComponent`), acompanhado de popover informativo `(i)` com atalho `?foco=palavras_chave_sorteio` que destaca o campo alvo em `/meu-perfil`.

### 1.4. Onboarding Limpo ("Zero Edições Versionadas") e DX Multiplataforma
Modificações atuais no working tree para primeira instalação limpa:
- **`install.js` + `package.json`**: substituiu chamadas diretas a `python backend/tools/install_portal_clis.py` nos scripts `npm run install:all` e `npm run install:portals` por orquestrador Node (`install.js`), com detecção automática de `.venv` (`findPython`).
- **`dev.js`**: reutiliza `findPython`, restringe a limpeza de portas (`killPort`) ao Windows (`if (process.platform !== 'win32') return;`) e sobe o backend Uvicorn com `--reload` observando `backend/api`, `backend/core`, `backend/db` e `backend/tools`.
- **`.env` na raiz e templates LaTeX limpos**: `backend/tools/ai_providers.py` prioriza a leitura combinada de `.env` na raiz (base em `.env.example`, removendo `backend/.env.example`) e fallback em `backend/.env`; foram restaurados `backend/cv/main_example.tex` e `backend/cover_letters/cover_example.tex`, além da anonimização de `backend/cv/reference_template.tex` e cobertura pelo novo teste `backend/tests/test_minimal_first_install.py`.

### 1.5. Modularização do Frontend, Segurança Bootstrap e Constantes do Backend
- **Constantes compartilhadas (`backend/core/constants.py`)**: centralização de `HIGH_FIT_MIN_SCORE` (`75`), `MED_FIT_MIN_SCORE` (`60`), `AUTO_SCORE_MIN`/`MAX`/`DEFAULT` (`45`/`95`/`60`), `ALLOWED_DOC_EXTS`, `PROTECTED_DOC_STEMS`, `resolve_safe_document_path` e `atomic_write_json`.
- **Novos endpoints REST no backend** ainda não listados em `docs/ARQUITETURA_PAINEL.md`:
  - `GET /api/token`, `POST /api/profile/organize`, `GET /api/cv-areas`
  - `POST /api/saved/batch-discard`, `POST /api/saved/batch-reevaluate`, `GET /api/saved/batch-status`, `POST /api/jobs/liveness`, `POST /api/discarded/clear`
  - `POST /api/applied/batch`, `POST /api/applications/reopen-recruiter`
  - `POST /api/recruiters/dismiss-batch` e grupo `/api/recruiters/linkedin/{status,connect,verify,config,disconnect}`
- **Arquitetura Frontend (`frontend/src/app/`)**: adição de `CsrfTokenService`, `authTokenInterceptor`, `ToastService`, desmembramento de `buscar-vagas` em `BuscarJobCardComponent`, `GeoMapComponent`, `SearchFiltersPanelComponent`, `JobBadgesComponent` e `PortalBadgeComponent`.
- **Padronização de CLIs de portais (`.agents/skills/`)**: `ashby-search`, `hn-search`, `jobicy-search` e `remoteok-search` foram consolidados no padrão `cli/` (`cli/package.json`, `cli/tsconfig.json`, `cli/tests/`), e `_portal-kit/src/helpers.ts` passou a aceitar campos opcionais/nulos.

---

## 2. Achados da Auditoria Inicial (Resolvidos na Seção 3)

> **Status:** Todos os achados listados abaixo foram analisados, aprovados e corrigidos antes do push conforme detalhado na **Seção 3**.

### 2.1. Inconsistências em Documentação Existente e Interface
1. **`SETUP.md:87` vs implementação real**: afirma que as chaves configuradas pela aba **Configurações** são salvas no SQLite local (`data/vagamundo.db`), porém `backend/api/routes/settings.py:35` + `backend/tools/ai_providers.py` gravam as credenciais no arquivo `.env` (`backend/.env` via `ENV_PATH`).
2. **`SETUP.md:120` vs `dev.js:12`**: informa que `npm run dev` libera portas residuais (`8765` e `4200`) em **Linux/macOS**, mas `killPort` em `dev.js:12` possui `if (process.platform !== 'win32') return;` (executa somente no Windows).
3. **`docs/ARQUITETURA_PAINEL.md:77` e `docs/SEGURANCA_E_WHITELABEL.md:28`**: continuam documentando `/api/session` (e atribuindo `/api/health` a `settings.py`), quando as rotas reais são `GET /api/token` (`backend/api/routes/settings.py:15`) e `GET /api/health` (`backend/api/routes/search.py:96`).
4. **`DATA_CONTRACT.md:30-35` e textos na UI**: listam diretórios inexistentes (`data/documents/`, `data/generated/`) e caminhos sem o prefixo `backend/` (`documents/cv/`, `documents/linkedin/`, `documents/perfil/respostas.json` em `DATA_CONTRACT.md:34-35`; `cv/`, `cover_letters/`, `documents/interview/` em `frontend/src/app/features/curriculos-cartas/curriculos-cartas.component.html:6`; `documents/linkedin` e `01-candidate-profile.md` em `frontend/src/app/features/evolucao/evolucao.component.ts:35-36`).

### 2.2. Pontos Legados de Caminhos (`tools/` na Raiz) e Regras de Segurança
1. **Referências à pasta removida `tools/`**: após a modularização para `backend/tools/`, não existe diretório `tools/` na raiz, mas o caminho legado permanece em `.claude/commands/*.md`, `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`, `.claude/settings.json` (`Bash(python tools/...:*)` e `Edit(tools/security_guards.py)`), `backend/tools/README_SALARY_TOOL.md:72`, `.github/workflows/upstream-watch.yml` e `backend/tools/security_guards.py:89-134` (os testes em `backend/tests/` contornam via shim em `backend/tests/_repo.py`).
2. **`backend/tools/security_guards.py:146-224`**:
   - `REQUIRED_DENY_RULES` e `.claude/settings.json` bloqueiam `Read(.env)` e `Read(.env.*)` na raiz, sem entrada explícita para `backend/.env`.
   - `REQUIRED_IGNORE_RULES` valida apenas os padrões legados na raiz (`cv/main_*.*`, `documents/perfil/**`), sem exigir explicitamente as regras reais `backend/cv/main_*.*`, `backend/documents/perfil/**` e `data/`.

### 2.3. Preservação de Whitelabel e Hardcoding Residual
A estrutura principal de dados pessoais (`skip-worktree`, `.gitignore` e `check_privacy.py`) permanece íntegra, sem PII versionado, porém existem violações funcionais de whitelabel no código:
1. **`backend/tools/google_careers.py`**:
   - Linha `441`: chama `posting_signals.analyse(..., accept={"junior", "pleno", "especialista"})` hardcoded em vez de consultar a senioridade configurada no perfil.
   - Linhas `128` e `194-208`: aplica `score = 25` (`vaga exclusiva afirmativa`) para `"for women in tech"` incondicionalmente, ignorando o gênero cadastrado no perfil.
   - Linhas `176`, `233`, `270`, `302-311`: queries padrão e critérios restritos a Ciência da Computação / Engenharia de Software.
2. **`backend/tools/eures.py:502` e `:354`**: descarta anúncios quando `not is_tech_role(...)` mesmo após consultar `_profile_eures_keywords()` do perfil do candidato (além de fallback fixo de stack tech na linha `354`).
3. **`backend/tools/ia/triage.py:16, 46-48, 597` e `backend/tools/ia/doc_builder.py:218`**:
   - Prompts de triagem e avaliação incluem exemplos específicos de transição de framework (`React/Vue` vs domínio em `Angular + TypeScript + SPA e backend/IA/SQL`).
   - `_LOW_YIELD_SEARCH_TERMS` em `triage.py:46-48` contém frases específicas em português (`"arquitetura front-end modular"`, `"sistemas erp corporativos"`, `"ocr e processamento de imagens"`).
4. **Exemplos ilustrativos de tecnologia**: placeholders em `backend/tools/painel_perfil.py:63`, `backend/tools/ia/doc_builder.py:709` e `frontend/src/app/features/recrutadores/recrutadores.component.html:37` utilizam exemplos da área de software (`Python`, `Angular`, `FastAPI`, `Spring Boot`, `Computer Vision`).

### 2.4. Resultados de Auditoria Estática (*SkillSpector* `v2.12.0` `--no-llm`)
- **`.claude/skills`**: Exit `0` — 3 skills (`job-application-assistant`, `scrape` [`job-scraper`], `upskill`), todas `0/100 (LOW) - SAFE`, `0` achados.
- **`.agents/skills`**: Exit `1` nas 24 skills:
  - **15 skills `26/100 (MEDIUM)`**: apenas `LP1` (`env`/`network` na CLI) e `SC1` (`"typescript": "^5.4.0"` em `cli/package.json:19`).
  - **3 skills `38/100 (MEDIUM)`** (`freehire-search`, `gupy-search`, `solides-search`): `2x LP1` + `SC1`.
  - **1 skill `36/100 (MEDIUM)`** (`remotar-search`): `LP1`, `3x E1`, `SC1`.
  - **5 skills `CRITICAL` localmente**: `ashby-search` (`89/100`), `hn-search` (`83/100`), `jobicy-search` (`83/100`), `programathor-search` (`83/100`), `remoteok-search` (`83/100`). Cada uma apresentou `284` achados `SC9` causados exclusivamente pela presença local da pasta não versionada `cli/node_modules/` (ignorada pelo `.gitignore`; além de `_portal-kit/node_modules`).

### 2.5. Teste com Chamada de Rede Externa Sem Mock (`test_linkedin_browser.py`)
- Em `backend/tests/test_linkedin_browser.py:556-566` (`test_sync_from_linkedin_handles_batch_without_any_emails`), o teste instancia `RecruiterService(..., enable_live_feeds=False)` e executa `svc.sync_all(query="React")` sem mockar `sync_from_hn`. Na execução anterior da suíte, a chamada externa ao Hacker News sofreu timeout (`The read operation timed out`), causando falha intermitente (`AssertionError: 1 != 0` em `res["errors"]`).

---

## 3. Correções Aplicadas Antes do Push (Plano Aprovado)

### 3.1. Unificação de `.env`, `dev.js` Multiplataforma e Sincronização de Docs/UI
- **`.env` único na raiz (`backend/tools/ai_providers.py`)**: `ENV_PATH` passou a apontar para `.env` na raiz (`REPO_ROOT / ".env"`), mantendo `LEGACY_ENV_PATH = ROOT / ".env"` apenas para fallback de leitura e espelhamento condicional em gravação se o arquivo legado já existir. Coberto em `EnvLoadingTests` (`backend/tests/test_minimal_first_install.py`).
- **`dev.js`**: `killPort` passou a suportar liberação de portas tanto no Windows (`netstat` + `taskkill`) quanto em macOS/Linux (`lsof` / `fuser`).
- **Documentação e interface sincronizadas**: corrigidos [`SETUP.md`](../SETUP.md), [`DATA_CONTRACT.md`](../DATA_CONTRACT.md), [`docs/ARQUITETURA_PAINEL.md`](ARQUITETURA_PAINEL.md), [`docs/SEGURANCA_E_WHITELABEL.md`](SEGURANCA_E_WHITELABEL.md), [`curriculos-cartas.component.html`](../frontend/src/app/features/curriculos-cartas/curriculos-cartas.component.html) e [`evolucao.component.ts`](../frontend/src/app/features/evolucao/evolucao.component.ts) para refletir as rotas reais (`GET /api/token`, `GET /api/health`) e os caminhos sob `backend/` (`backend/cv/`, `backend/cover_letters/`, `backend/documents/perfil/`).

### 3.2. Eliminação de Caminhos Legados (`tools/` → `backend/`) e Hardening de Segurança
- **`.claude/`, CI e ferramentas Python**: migradas referências de `tools/`, `salary_lookup.py`, `cv/`, `cover_letters/` e `documents/` para `backend/...` em [`.claude/settings.json`](../.claude/settings.json), [`.claude/agents/`](../.claude/agents/), [`.claude/commands/`](../.claude/commands/), [`.claude/skills/`](../.claude/skills/), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), [`.github/workflows/upstream-watch.yml`](../.github/workflows/upstream-watch.yml), [`backend/salary_lookup.py`](../backend/salary_lookup.py), [`backend/tools/README_SALARY_TOOL.md`](../backend/tools/README_SALARY_TOOL.md), [`backend/tools/compile_doc.py`](../backend/tools/compile_doc.py), [`backend/tools/painel.py`](../backend/tools/painel.py) e nos testes em [`backend/tests/`](../backend/tests/).
- **`framework_version`**: incrementadas as versões nos arquivos editados sob `.claude/skills/job-application-assistant/` e validadas com `check_framework_version.py`.
- **`backend/tools/security_guards.py`**: exigência explícita para `backend/.env` em `REQUIRED_DENY_RULES`, para `backend/cv/main_*.*`, `backend/documents/perfil/**` e `data/` em `REQUIRED_IGNORE_RULES`, e validação canônica de scripts sob `backend/tools/`.

### 3.3. Preservação Completa de Whitelabel e Generalidade
- **[`backend/tools/google_careers.py`](../backend/tools/google_careers.py)**: substituídos `accept` fixo e termos exclusivos de computação por leitura dinâmica de senioridade, cargos, palavras-chave (`_load_profile_prefs`, `_profile_terms`) e `genero` do perfil (aplicando penalidade de vaga afirmativa exclusiva apenas quando incompatível e aviso consultivo quando `genero` não estiver informado).
- **[`backend/tools/eures.py`](../backend/tools/eures.py)**: adicionadas `_profile_eures_keywords()` e `_queries_expect_tech()` para que perfis não técnicos mantenham resultados da própria área em `fetch_eures_for_panel()`, preservando o filtro `is_tech_role` somente quando os termos ativos indicarem tecnologia.
- **Prompts e placeholders neutros**: removidos exemplos específicos de stack pessoal e termos rígidos em [`backend/tools/ia/triage.py`](../backend/tools/ia/triage.py), [`backend/tools/ia/doc_builder.py`](../backend/tools/ia/doc_builder.py), [`backend/tools/painel_perfil.py`](../backend/tools/painel_perfil.py) e [`recrutadores.component.html`](../frontend/src/app/features/recrutadores/recrutadores.component.html).
- **Novos testes whitelabel**: adicionados `test_google_careers_respects_candidate_gender_on_affirmative_roles` e `test_eures_non_tech_profile_allows_non_tech_results` em [`backend/tests/test_minimal_first_install.py`](../backend/tests/test_minimal_first_install.py).

### 3.4. Confiabilidade de Rede em Testes, Limpeza das CLIs e Reauditoria *SkillSpector*
- **`RecruiterService` e testes (`backend/core/recruiter_service.py`, `backend/tests/test_linkedin_browser.py`)**: garantido que `sync_from_hn` só seja acionado em `sync_all()` quando `enable_live_feeds=True`, com mocks explícitos no teste paralelo para eliminar chamadas de rede reais na suíte.
- **Limpeza de `node_modules` nas CLIs**: após validar `bun run typecheck` (`tsc --noEmit`) e `bun test` nas 5 CLIs TypeScript afetadas (`ashby-search`, `hn-search`, `jobicy-search`, `programathor-search` — com `13 pass` e `1 skip` em `live.test.ts` — e `remoteok-search`), todos os diretórios locais `node_modules` em `.agents/skills/` foram removidos do workspace.
- **Reauditoria *SkillSpector* `v2.12.0` (`--recursive --no-llm --format json`)**:
  - `.claude/skills`: **Exit `0`** — 3/3 skills `0/100 (LOW)`, `0` achados.
  - `.agents/skills`: **Exit `0`** — 24/24 skills em `MEDIUM` (scores entre `26/100` e `38/100`, `2` a `3` achados por skill, `successful`), **0 CRITICAL** e **0 HIGH**.
