# Radar de Recrutadores e Modo Automático Contínuo

Este documento detalha os dois módulos introduzidos para acelerar a prospecção ativa de oportunidades e a triagem automatizada com proteção contra bloqueios externos.

---

## 1. Radar de Recrutadores (`backend/core/recruiter_service.py` + `/recrutadores`)

O Radar de Recrutadores centraliza oportunidades que expõem **e-mail direto (`@`)** da pessoa recrutadora ou da empresa contratante, permitindo envio direto com controle de histórico.

### 1.1 Fontes Mineradas (`RecruiterService.sync_all`)
A coleta consolida múltiplas origens com cache temporário por feed (`_get_cached_feed` / `_set_cached_feed`) e deduplicação por URL e e-mail:

1. **Banco local (`sync_from_jobs` e `sync_from_recent_scrapes`):** Minera e-mails embutidos em descrições de vagas já coletadas pelos 24 portais CLI ou em varreduras recentes (`scan_runs`).
2. **Hacker News — *Who is Hiring* (`sync_from_hn`):** Consulta a API pública do HN Algolia (`hn.algolia.com/api/v1/...`), extrai metadados estruturados (`_parse_hn_header_meta`) e aplica `_is_hn_candidate_seeking_post` para descartar comentários de profissionais procurando emprego.
3. **GitHub Vagas BR (`sync_from_github_repos`):** Lê *issues* abertas de repositórios públicos listados em `RECRUITER_GITHUB_REPOS` (suporta opcionalmente `GITHUB_TOKEN` ou `GH_TOKEN` no ambiente para ampliar cota da API do GitHub).
4. **Remotive (`sync_from_remotive`):** Consulta vagas remotas públicas em `https://remotive.com/api/remote-jobs` que contenham endereço de contato direto.
5. **Coleta em portais ao vivo (`sync_from_live_portals`) e colagem manual (`add_pasted_post`):** Permite acionar varreduras focadas por palavra-chave ou colar manualmente um anúncio (ex.: post do LinkedIn) via `POST /api/recruiters/paste`.
6. **Publicações do LinkedIn com perfil isolado (`sync_from_linkedin_browser` / `backend/core/linkedin_browser.py`):** Coleta publicações de contratação no LinkedIn usando sessão local isolada em `data/browser_profile/` (fora do Git), com filtro limpo por palavra-chave e `datePosted` (`past-24h`, `past-week`, `past-month`), suporte a triagem sob demanda via `POST /api/recruiters/triage` e importação automática também para publicações válidas com link direto sem e-mail literal.

### 1.2 Higienização de E-mails e Trecho de Contexto
- `extract_clean_emails(text)` remove endereços inválidos, placeholders genéricos, sufixos truncados ou arquivos de imagem/extensões confundidas com e-mail.
- `extract_email_context(text, email)` extrai o trecho imediatamente ao redor do e-mail encontrado para exibir no card **como e para quem** enviar a mensagem sem precisar abrir toda a postagem.
- Se houver múltiplos e-mails, a triagem de IA elege `ai_best_email`, exibindo a pílula **Principal** no chip correspondente.

### 1.3 Histórico Anti-Duplicação (`application_ledger`)
Ao clicar em um chip de e-mail em `RecrutadoresComponent`:
1. O endereço é copiado para a área de transferência e surge um lembrete contextual (**"Já mandei e-mail"**).
2. Ao confirmar, `mark_post_contacted` grava simultaneamente na tabela `recruiter_posts`, cria/atualiza candidatura e registra entrada imutável em `application_ledger`.
3. Em futuras buscas ou publicações da mesma empresa/endereço, `previously_contacted` é preenchido automaticamente com data e empresa já contatadas, evitando abordagens repetidas ao mesmo recrutador.

### 1.4 Calibração da Triagem IA e Limpeza de Filtros
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
- **Modo Recrutadores (`start_recruiters`):** Sorteia **1 palavra-chave focalizada** do CV por rodada, sincroniza/minera posts com e-mail, realiza triagem em lote (`_screen_one_recruiter`), classifica `nao_e_vaga` ou bancos de talentos e promove vagas compatíveis (`promote_post_to_interested`).

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
