# Radar de Recrutadores e Modo Automático Contínuo

Este documento detalha os dois módulos introduzidos para acelerar a prospecção ativa de oportunidades e a triagem automatizada com proteção contra bloqueios externos.

---

## 1. Radar de Recrutadores (`backend/core/recruiters/*` + `/recrutadores`)

O Radar de Recrutadores é organizado modularmente em `backend/core/recruiters/` (`service.py`, `collectors.py`, `parser.py`, `triage.py`, `search_terms.py`, com fachada compatível em `backend/core/recruiter_service.py`) e centraliza oportunidades que expõem **e-mail direto (`@`)** da pessoa recrutadora ou da empresa contratante, além de posts do LinkedIn avaliados inline pela IA.

### 1.1 Fontes Mineradas (`RecruiterService.sync_all` e `collectors.py`)
A coleta consolida múltiplas origens com cache temporário por feed (`_get_cached_feed` / `_set_cached_feed`) e deduplicação por URL e e-mail:

1. **Banco local (`sync_from_jobs` e `sync_from_recent_scrapes`):** Minera e-mails embutidos em descrições de vagas já coletadas pelos portais CLI ou em varreduras recentes (`painel_busca_*.json`), alimentando `portal_breakdown` via `_status_out`.
2. **Hacker News — *Who is Hiring* (`sync_from_hn`):** Consulta a API pública do HN Algolia (`hn.algolia.com/api/v1/...`), extrai metadados estruturados (`_parse_hn_header_meta`) e aplica `_is_hn_candidate_seeking_post` para descartar comentários de profissionais procurando emprego.
3. **GitHub Vagas BR (`sync_from_github_repos`):** Lê *issues* abertas de repositórios públicos listados em `RECRUITER_GITHUB_REPOS` (suporta opcionalmente `GITHUB_TOKEN` ou `GH_TOKEN` no ambiente para ampliar cota da API do GitHub).
4. **Remotive (`sync_from_remotive`):** Consulta vagas remotas públicas em `https://remotive.com/api/remote-jobs` que contenham endereço de contato direto.
5. **Coleta em portais ao vivo (`sync_from_live_portals`) e colagem manual (`add_pasted_post`):** Aciona em paralelo (até 8 workers, timeout de 30s) os 9 portais CLI com descrição completa listados em `RECRUITER_LIVE_PORTALS` (`remotar-search`, `freehire-search` — com chamadas `--country`, `--remote` e `--limit 50` global —, `remoteok-search`, `solides-search`, `gupy-search`, `greenhouse-search --with-description`, `ashby-search`, `jobicy-search` e `empregos-search --with-description`), com deduplicação por `(portal, url)`, ou permite colar manualmente um anúncio via `POST /api/recruiters/paste`.
6. **Barra de Pesquisa LinkedIn Enxuta e Avaliação Inline por IA (`LinkedinSearchBarComponent` + `linkedin-search-formatter.util.ts` + `bilingual-terms.util.ts` + `/paste` / `/paste-batch`):**
   - **Zero automação autenticada / zero risco de banimento:** Não há worker CDP nem login automatizado no LinkedIn. A barra no topo de `/recrutadores` (`frontend/src/app/features/recrutadores/components/linkedin-search-bar/`) opera de forma 100% segura.
   - **Sorteio automático do CV no topo:** Ao abrir a tela (ou clicar em **Sortear área CV**), o componente sorteia automaticamente uma palavra-chave do perfil do candidato para já iniciar com uma busca pronta.
   - **Queries enxutas (máx. 4 operadores booleanos):** O gerador (`linkedin-search-formatter.util.ts`) limita a consulta a no máximo **4 operadores booleanos (`AND`/`OR`)**, evitando o bug conhecido do feed do LinkedIn que retorna resultados vazios ou irrelevantes em expressões booleanas longas.
   - **Suporte Whitelabel Bilíngue (PT↔EN) + Expansão por IA para qualquer profissão:** Combina dicionário estático instantâneo (`bilingual-terms.util.ts`, cobrindo tecnologia, gestão, finanças, agronegócio, marketing, saúde, engenharia, etc.) com o endpoint `POST /api/recruiters/expand-search-term` (`backend/core/recruiters/search_terms.py`), que consulta a IA configurada (com cache em memória e degradação silenciosa) para parear qualquer termo em português com seu equivalente de mercado em inglês (`("Termo PT" OR "Term EN")`).
   - **Presets focados:**
     - `Vagas` (`vagas_geral`): Termo principal (+ variação PT/EN) + `("vaga" OR "hiring")` + filtro enxuto de modalidade/região.
     - `Hiring + E-mail` (`vagas_email`): Termo principal (+ variação PT/EN) + `("hiring" OR "arroba" OR "email")`, ideal para achar posts de recrutadores com contato direto no corpo do post.
     - `E-mail / CV` (`recrutadores_cv`): Termo principal + `("envie seu currículo" OR "send your resume" OR "email")`.
     - `Só termos` (`somente_termos`): Apenas o termo principal (e sua variação bilíngue quando ativa).
   - **Link direto LinkedIn + Fallback Google X-Ray:** Gera tanto a URL nativa do feed do LinkedIn (`https://www.linkedin.com/search/results/content/?keywords=...&sortBy=%22date_posted%22`) quanto o link **Google X-Ray** (`site:linkedin.com/posts OR site:linkedin.com/feed/update ...`) para contornar limites de busca do LinkedIn.
   - **Avaliação Inline da IA abaixo da caixa de colagem (`allow_without_email=true`):** Ao colar 1 ou vários posts do LinkedIn (separados por `---`) na caixa de colagem, o backend (`POST /api/recruiters/paste` ou `/paste-batch` com `allow_without_email=True`, decodificando a data real via Snowflake ID da URL do LinkedIn) salva e aciona imediatamente a triagem da IA. Os resultados aparecem **inline logo abaixo da caixa de colagem** com nota de aderência (`ai_score`), veredito resumido, e-mails extraídos (se houver) e botões diretos **"Me interessa"** (`POST /api/recruiters/{post_id}/interested`) e **"Descartar"** (`DELETE /api/recruiters/{post_id}`).
7. **Telemetria multiplataforma (`portal_breakdown` / `.multiplatform-radar-bar`):** `RecruiterService.sync_all` e `AutoModeService` (`round_portal_breakdown` e `round_warnings`) consolidam por plataforma as contagens `fetched`, `matched`, `errors` e `last_error`, exibidas na barra `.multiplatform-radar-bar` com filtro rápido por plataforma (`togglePortalQuickFilter`).

### 1.2 Higienização de E-mails e Trecho de Contexto
- `extract_clean_emails(text)` remove endereços inválidos, placeholders genéricos, sufixos truncados ou arquivos de imagem/extensões confundidas com e-mail.
- `extract_email_context(text, email)` extrai o trecho imediatamente ao redor do e-mail encontrado para exibir no card **como e para quem** enviar a mensagem sem precisar abrir toda a postagem.
- Se houver múltiplos e-mails, a triagem de IA elege `ai_best_email`, exibindo a pílula **Principal** no chip correspondente.

### 1.3 Histórico Anti-Duplicação (`application_ledger`)
Ao clicar em um chip de e-mail em `RecrutadoresComponent`:
1. O endereço é copiado para a área de transferência e surge um lembrete contextual (**"Já mandei e-mail"**).
2. Ao confirmar, `mark_post_contacted` grava simultaneamente na tabela `recruiter_posts`, cria/atualiza candidatura e registra entrada imutável em `application_ledger`.
3. Em futuras buscas ou publicações da mesma empresa/endereço, `previously_contacted` é preenchido automaticamente com data e empresa já contatadas, evitando abordagens repetidas ao mesmo recrutador.

### 1.4 Calibração da Triagem IA, Isolamento de Rodada, Paginação e Fluxo para Descartadas
- **Atuais encontrados isolado por busca/rodada e filtro padrão de período aberto:** Ao abrir `/recrutadores` sem busca manual na sessão nem rodada ativa do Modo Automático, a coluna **Atuais encontrados** inicia vazia; durante uma busca manual (`matched_post_ids`) ou rodada automática (`round_post_ids`), exibe exclusivamente os anúncios da busca/rodada corrente. O filtro de período `jobAgeFilter` inicia em `''` (*Todas as datas*, preservando postagens externas com data de publicação anterior a 24h, enquanto o usuário pode restringir manualmente para `1`, `7` ou `30` dias). **Histórico de vagas relevantes** acumula todas as `vaga_ativa` já triadas entre rodadas com **paginação** configurável (`10`, `20` ou `50` itens por página) e seleção em lote preservada entre páginas.
- **Permanência uniforme entre todas as plataformas:** Publicações promovidas para *Me Interessam* (`auto_promoted=1` / `job_status='interested'`) e anúncios classificados como `banco_talentos` (`auto_dismissed=False`) permanecem visíveis no Radar (`list_recruiter_posts` e `_is_row_visible_in_radar`) em **todas as plataformas** (LinkedIn e portais externos como `freehire-search`, `hn-search`, `solides-search`, `github-vagas`, `remotive-search`, etc.) até ação manual do usuário (descartar, enviar para Descartadas, pular ou registrar candidatura).
- **Ordenação por detecção recente, filtro por nota e link original:** o **Histórico de vagas relevantes** inicia ordenado por **Mais recentes detectadas** (`created_at` → `ai_evaluated_at` → `published_date`) e disponibiliza controles persistidos (`RecruiterStateService`) para alternar para **Melhores notas (IA)** e filtrar por faixa (`Todas`, `>= 60`, `>= 75`). Em todas as plataformas com URL HTTP(S) válida, os cards exibem o botão explícito **Ver post original** (`.btn-footer-view-post`), normalizando URLs relativas `/posts/` e `/feed/update/` do LinkedIn e exibindo `Sem URL externa` quando não houver link válido.
- **Envio reversível para Descartadas e exclusão definitiva do BD:** Ao clicar em **Descartar** (individualmente ou em lote via `POST /api/recruiters/dismiss-batch`), a publicação é vinculada a um registro `jobs.status = 'discarded'` e passa a ser exibida na aba **Descartadas** (`/descartadas`, mantendo a trava contra reimportação da mesma vaga). Ao promover para **Me Interessam** ou enviar para **Descartadas** (e ao **Restaurar**), `_prepare_job_from_post` e `_record_post_evaluation` preservam integralmente `location`, `work_model`, `posted_date`, `description`, `portal` e os critérios estruturados da avaliação (`subscores`, `strengths`, `gaps`, gates e `ai_model`). Na aba Descartadas, também é possível usar **Excluir do BD** (`POST /api/discarded/delete` / **Limpar lista** via `POST /api/discarded/clear`) para apagar permanentemente a vaga, o vínculo `recruiter_posts`, avaliações e o histórico em `seen_jobs.json`. Vagas já com `status = 'applied'` preservam seu status aplicado.
- **Busca focalizada e sem confusão visual:** Foram removidos o badge paralelo de *"100% match"* (que confundia com a nota da IA) e o dropdown redundante de filtro por nota dentro da aba `/recrutadores`. O campo principal recomenda **1 palavra-chave ou tecnologia focalizada por vez** (ou termos separados por vírgula), com o botão **Sortear área CV** (`pickRandomCvArea`).
- **Calibração no backend (`backend/tools/painel_ia.py`):**
  - `_compact_candidate_profile(language, max_chars)` sintetiza o perfil do candidato garantindo que experiência, formação e habilidades centrais cheguem íntegras no prompt sem cortes aleatórios.
  - `_apply_seniority_ceiling` calibra o teto de nota quando há incompatibilidade real de senioridade (ex.: vagas *Staff/Principal* diante de perfil júnior/pleno, e vice-versa).
  - Classificação explícita entre `vaga_ativa` e `nao_e_vaga` (posts de portfólio, propaganda, banco de talentos genérico ou candidatos se divulgando), permitindo ocultar facilmente o ruído com o checkbox **Ocultar "Não é vaga"**.

---

## 2. Modo Automático Contínuo (`backend/core/auto_mode.py` + `AutoModeService`)

O orquestrador automático roda em **thread daemon no backend**, mantendo estado global (`AutoModeService` no Angular) visível no `AutoModeBannerComponent` em todas as 10 rotas do painel.

### 2.1 Modos de Operação
- **Modo Vagas (`start`):** Sorteia áreas do currículo (`_pick_keywords_for_round`), executa varredura multi-portal, avalia com IA contra o perfil, move automaticamente notas >= `min_score` para **Me Interessam** e descarta incompatibilidades evidentes.
- **Modo Recrutadores (`start_recruiters`):** Sorteia **1 palavra-chave focalizada** do CV por rodada, sincroniza/minera em paralelo todas as fontes públicas monitoradas sem login (HN, GitHub Vagas BR, Remotive, 9 portais CLI ao vivo, banco local e varreduras recentes), registra os IDs encontrados em `round_post_ids`, realiza triagem em lote (`_screen_one_recruiter`), classifica `nao_e_vaga` ou bancos de talentos e promove vagas compatíveis (`promote_post_to_interested`). Posts colados manualmente do LinkedIn via `/paste` ou `/paste-batch` acordam o cooldown automaticamente via `enqueue_recruiter_posts`.

### 2.2 Ciclo Contínuo e Proteção Anti-Ban
Quando a opção **Contínuo** está habilitada (`continuous=true`), ao concluir uma rodada o servidor entra em fase de espera segura antes de sortear a próxima área do currículo (evitando histórico recente armazenado no perfil):

| Parâmetro (`backend/core/auto_mode.py`) | Modo Vagas (`jobs`) | Modo Recrutadores (`recruiters`) |
| :--- | :--- | :--- |
| Intervalo padrão (`DEFAULT`) | `300s` (5 min) | `30s` |
| Faixa permitida (`MIN` – `MAX`) | `120s` – `1800s` | `15s` – `300s` |
| Jitter + Backoff Anti-Ban | Sim (`_compute_cooldown`) | Sim (`_compute_cooldown`) |
| Limite de falhas fatais consecutivas | `MAX_CONSECUTIVE_FATAL_ERRORS = 5` | `MAX_CONSECUTIVE_FATAL_ERRORS = 5` |

- **Detecção de Rate-Limit (`_detect_rate_limit_in_portals`):** Erros `429` ou bloqueios externos ampliam automaticamente o intervalo de espera (*backoff*), exibindo o motivo claro no banner global.
- **Controles do Usuário em Tempo Real:**
  - **Pular espera** (`POST /api/auto-mode/skip-cooldown`): acorda imediatamente o `_skip_cooldown_event` sem cancelar a execução contínua.
  - **Parar agora** (`POST /api/auto-mode/cancel`): interrompe de forma limpa ao fim da operação atômica corrente.
  - **Desfazer (`undo_run` / `undo_job`):** Reverte promoções/descartes de uma rodada inteira ou de uma vaga individual, restaurando o estado anterior no SQLite.
