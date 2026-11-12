# ADR 004: Persistência de Estado no Cliente, Ledger Imutável e Loop Autônomo Server-Side

## Contexto

Com a evolução do painel Web para múltiplas rotas (Dashboard, Buscar e Vagas, Recrutadores, Candidaturas, Descartadas) e a adição de automações longas (varreduras em 24 portais + triagem IA), surgiram três limitações arquiteturais:
1. Ao trocar de aba/rota no Angular, componentes eram destruídos e recriados, descartando filtros digitados, seleção de portais e lista carregada.
2. No fluxo de contatos diretos por e-mail (`/recrutadores`), mover ou descartar vagas podia apagar a visibilidade de empresas/recrutadores já abordados, gerando risco de recontato duplicado.
3. Um loop de busca e triagem guiado exclusivamente por timers no navegador congelava ou encerrava sempre que o usuário navegava para outra aba, fechava o modal ou sofria uma queda momentânea de conexão.

## Decisão

1. **Estado reativo global em Angular Signals + `localStorage`:**
   - Criar serviços *singleton* `SearchStateService` (`vagamundo.searchState.v1`) e `RecruiterStateService` (`vagamundo.recruiterState.v1`), além de `ThemeService` (`vagamundo_theme`), hidratando e persistindo preferências e resultados automaticamente entre navegações e recarregamentos.
2. **Livro-razão imutável no SQLite (`application_ledger`):**
   - Registrar de forma permanente cada e-mail/candidatura contatado em `application_ledger`, permitindo que o Radar de Recrutadores alerte em futuras buscas (`previously_contacted`) mesmo após alterações de status nas tabelas de trabalho.
3. **Orquestração Autônoma no Servidor (`backend/core/auto_mode.py`):**
   - Executar os modos contínuos de **Vagas** (`jobs`) e **Recrutadores** (`recruiters`) em thread daemon gerenciada pelo backend FastAPI, com persistência de histórico de palavras-chave no SQLite (`profile`), intervalos mínimos anti-ban, backoff automático em erro de rede/rate-limit, `skip_cooldown`, cancelamento gracioso e reversão atômica (`undo_run` / `undo_job`).
   - Expor o estado via polling em `AutoModeService` e barra global `AutoModeBannerComponent` visível em todas as rotas.

## Consequências

- **Positivas:** Navegação instantânea sem perda de filtros, eliminação prática de reenvio duplicado de e-mails a recrutadores, e automação resiliente capaz de rodar continuamente em segundo plano mesmo enquanto o usuário gerencia candidaturas em outras abas.
- **Atenção:** Alterações nos formatos salvos em `localStorage` devem manter compatibilidade defensiva na hidratação (validando listas/valores permitidos ao carregar).
