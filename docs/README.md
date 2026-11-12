# Documentação Técnica — Vagamundo

Este diretório concentra a documentação arquitetural, funcional e de segurança do **Vagamundo**. Os textos são mantidos sincronizados com o código-fonte para que **qualquer colega ou agente de IA** consiga ler esta pasta e compreender o sistema completo — incluindo regras de whitelabel, segurança e fluxos autônomos — antes de executar ou alterar o projeto.

---

## Onboarding Rápido para Colegas e Agentes de IA

Se você (ou um agente de IA em seu nome) acabou de clonar ou atualizar o repositório, siga esta ordem de leitura:

1. **Regras e Fonte da Verdade do Workspace:**
   - [AGENTS.md](../AGENTS.md) — Define o idioma padrão (`pt-BR`), os ponteiros finos e as camadas de configuração.
   - [CLAUDE.md](../CLAUDE.md) e [SETUP.md](../SETUP.md) — Perfil da pessoa candidata e passo a passo de personalização via `/setup`.
   - [.claude/skills/](../.claude/skills/) e [.claude/commands/](../.claude/commands/) — Especificações canônicas dos comandos (`/setup`, `/scrape`, `/rank`, `/apply`, `/upskill`, `/interview`, `/reset`).
2. **Arquitetura e Fluxos Web (leitura recomendada nesta pasta):**
   - [Arquitetura do Painel Web Local](ARQUITETURA_PAINEL.md) — Stack Angular + FastAPI, 10 rotas da UI, 24 portais CLI, 9 tabelas SQLite, endpoints REST e `dev.js`.
   - [Radar de Recrutadores e Modo Automático Contínuo](RADAR_RECRUTADORES_E_MODO_AUTOMATICO.md) — Mineração de e-mails diretos, prevenção de recontato, calibração de triagem por IA e loop autônomo anti-ban.
   - [Segurança, Whitelabel e Privacidade Pré-Push](SEGURANCA_E_WHITELABEL.md) — `skip-worktree`, `check_privacy.py`, SSRF/TLS, Host Check, CSRF, Path Containment e auditoria com NVIDIA SkillSpector.
   - [ADR 004: Persistência de Estado e Loop Autônomo](adr/004-state-persistence-and-autonomous-loop.md) — Decisões de persistência no navegador (`localStorage`), `application_ledger` e orquestração em segundo plano.

### Execução Local e Validação em 3 Comandos

```bash
# 1. Instalar dependências (raiz + frontend + CLIs conforme SETUP.md)
npm run dev
```

Para validar integridade, privacidade e testes antes de um `git push`:

```bash
python backend/tools/check_privacy.py
python backend/tools/security_guards.py
python backend/tools/lint_skills.py
python -m unittest discover -s backend/tests -t . -v
npm --prefix frontend test -- --watch=false --browsers=ChromeHeadless
```

---

## Resumo das Atualizações Recentes

Desde a linha de base anterior do painel, o projeto recebeu evoluções estruturais importantes:

- **Radar de Recrutadores e Histórico Anti-Duplicação (`backend/core/recruiter_service.py`, rota `/recrutadores`):**
  - Coleta unificada de posts com e-mail direto (`@`) a partir do banco local (`jobs`/`scan_runs`), HN *Who is Hiring*, repositórios públicos de vagas no GitHub Issues, API do Remotive e colagem manual.
  - Higienização estrita de e-mails (`extract_clean_emails`), exibição do trecho contextual ao redor do contato, lembrete instantâneo ao copiar o endereço e bloqueio visual de reenvio apoiado na tabela imutável `application_ledger`.
  - Remoção de badges confusos (*match* genérico) e do filtro redundante de nota em Recrutadores; priorização de busca por palavra-chave focalizada com sorteio de áreas do currículo.
- **Modo Automático Contínuo Anti-Ban (`backend/core/auto_mode.py`, `AutoModeBannerComponent`):**
  - Suporte aos modos `jobs` e `recruiters` em daemon no servidor, com alternância entre rodada única e execução contínua rotacionando áreas do CV sem repetir pares recentes.
  - Proteção anti-ban com intervalo configurável, jitter, backoff automático ao detectar `429`/rate-limit, botão manual para pular espera (`skip_cooldown`) e reversão atômica (`undo_run` / `undo_job`).
- **Persistência Reativa entre Rotas (`SearchStateService`, `RecruiterStateService`, `AutoModeService`):**
  - Filtros, portais selecionados e resultados permanecem preservados em Signals + `localStorage` ao navegar pelas 10 rotas do painel.
- **Hardening de Segurança e Whitelabel:**
  - Correção da validação do cabeçalho `Host` (incluindo IPv6 `[::1]` e bloqueio contra spoofing), contenção explícita de *path traversal* em `serve_spa`, bloqueio de SSRF e reativação de verificação TLS em `liveness.py` e `eures.py`, substituição de `innerHTML` por criação pura via DOM (`document.createElementNS`) nos mapas SVG, remoção de viés pessoal em `eures.py`, `google_careers.py` e testes, além do alinhamento completo das permissões dos 24 portais e pipeline CI.

---

## Índice de Documentos

1. [Arquitetura do Painel Web Local](ARQUITETURA_PAINEL.md)
   - Especificação do frontend Angular (`frontend/`), backend FastAPI (`backend/`), SQLite (`data/vagamundo.db`), rotas, endpoints e inicialização.
2. [Radar de Recrutadores e Modo Automático Contínuo](RADAR_RECRUTADORES_E_MODO_AUTOMATICO.md)
   - Pipeline de mineração de contatos com e-mail, calibração da triagem IA e máquina de estados do loop contínuo anti-ban.
3. [Mapa Mundial e Geolocalização de Oportunidades](MAPA_MUNDIAL_E_GEOLOCALIZACAO.md)
   - Mapa interativo SVG (27 UFs do Brasil e 172 países), resolução geográfica em `job-filters.util.ts` e renderização segura sem `innerHTML`.
4. [Integração Europeia (EURES) e Google Careers](INTEGRACAO_EURES_E_EUROPA.md)
   - Conectores `backend/tools/eures.py` e `google_careers.py`, verificação TLS e avaliação dinâmica baseada no perfil whitelabel.
5. [Integração da Rússia e Eurásia (HeadHunter e Habr Career)](INTEGRACAO_RUSSIA_E_EURASIA.md)
   - Skills `hh-search` e `habrcareer-search`, busca híbrida Inglês/Cirílico e auditoria SkillSpector.
6. [Segurança, Whitelabel e Privacidade Pré-Push](SEGURANCA_E_WHITELABEL.md)
   - Controles de privacidade, hardening HTTP/SSRF/XSS, allowlists de agentes e análise SkillSpector.
7. [Architecture Decision Records (ADRs)](adr/)
   - [ADR 001: SQLite como Store Primário](adr/001-sqlite-primary-store.md)
   - [ADR 002: FastAPI como Gateway da API Local](adr/002-fastapi-gateway.md)
   - [ADR 003: Coexistência de Dois Caminhos de IA (Dual-Path)](adr/003-dual-ai-path.md)
   - [ADR 004: Persistência de Estado e Loop Autônomo](adr/004-state-persistence-and-autonomous-loop.md)

---
Para orientações detalhadas de instalação e personalização inicial, consulte também o [README.md](../README.md) e o [SETUP.md](../SETUP.md).
