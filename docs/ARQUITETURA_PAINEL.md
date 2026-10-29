# Arquitetura do Painel Web Local

## 1. Princípios de Design

O painel de controle do `vagamundo` (`tools/painel.py` e `tools/painel/index.html`) opera como uma aplicação web monoliticamente servida em `127.0.0.1`, sem dependência de ferramentas pesadas de build ou frameworks compilados:
1. **Zero Node / Zero Webpack / Zero NPM no Runtime:** HTML, CSS e Vanilla JavaScript nativo com execução direta no navegador.
2. **Defesa em Profundidade contra XSS:**
   - Content Security Policy (CSP) restritiva com `default-src 'self'`.
   - Proibição absoluta de sinks perigosos de injeção (`innerHTML`, `outerHTML`, `document.write`, `eval`). Todo nó de dado é inserido via `textContent`, `setAttribute`, `replaceChildren` ou `document.createElement`.
3. **Proteção Anti-CSRF:**
   - Token secreto aleatório de sessão injetado na tag `<meta name="painel-token">` e exigido em todas as mutações (`POST`) via cabeçalho `X-Painel-Token`.
4. **Respeito à Privacidade e Whitelabel (100% Apropriável):**
   - A interface e os scrapers não contêm termos ou áreas fixas (hardcoded) específicas de um único candidato.
   - Todo dado e sugestão de palavras-chave é inferido dinamicamente a partir dos arquivos Markdown do perfil (`cv.md`, `CLAUDE.md`) ou `respostas.json`.
   - Nenhum dado pessoal da pessoa candidata é versionado no Git, mantendo conformidade com `tools/check_privacy.py`.

---

## 2. Estrutura de Abas e Subabas

A interface organiza-se em um fluxo de trabalho progressivo:
- **Buscar e Vagas (Aba Unificada):**
  - **Console de Filtros Inteligentes:**
    - **Input com Randomizador do CV:** Botão integrado com ícone de dados (🎲) para alternar e sugerir termos técnicos extraídos dinamicamente do currículo da pessoa usuária.
    - **Filtro Textual Abrangente:** O filtro de texto busca simultaneamente em título, empresa, localização, descrição completa da vaga, habilidades requeridas e tags associadas.
    - **Filtro de Nota Reativo:** O seletor de "Nota de Aderência (Fit IA)" ajusta-se automaticamente após o processo de triagem com IA.
    - **Reset Inteligente:** Empty-state cards intuitivos com botão "Limpar filtros" quando uma busca combinada não retorna vagas.
  - **Subaba 1 — Mapa Mundial & Estatísticas da Busca:**
    - Visualização interativa cartográfica do Mundo e do Brasil.
    - Badges com contagem de vagas e notas de triagem.
    - Barra de chips para vagas 100% remotas (Brasil, Europa e Global).
    - Polos com maior afinidade técnica ao currículo.
    - Gráficos de barras dinâmicos (Top localidades, Modelos de trabalho e Portais).
  - **Subaba 2 — Lista Completa de Vagas:**
    - Cards de vagas com sinalizações de golpe/alerta, chips de modelo, regime e botões de ação ("Me interessa" / "Descartar").
    - Barra de ações em lote para triagem automatizada com IA.
- **Me interessam:** Vagas salvas para aprofundamento, avaliação com IA e preparação de candidaturas.
- **Candidaturas:** Acompanhamento do pipeline de vagas enviadas, entrevistas e propostas.
- **Currículos e Cartas:** Hub de documentos LaTeX e PDFs gerados.
- **Descartadas:** Histórico de vagas descartadas com opção de restauração.
- **Configurações:** Seleção e teste de motor de IA (Gemini, Claude ou OpenAI).

---

## 3. Endpoints da API HTTP Local

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/` | Serve a interface web `tools/painel/index.html` com injeção do token |
| `GET` | `/api/status` | Estado dos processos em segundo plano (busca, triagem, provedor de IA) |
| `GET` | `/api/results` | Lista de vagas novas encontradas e não marcadas |
| `GET` | `/api/saved` | Vagas marcadas como "Me interessa" com notas e PDFs associados |
| `GET` | `/api/geo` | Dados vetoriais SVG do Brasil (27 UFs) e Mundo (172 países) |
| `GET` | `/api/eures/stats` | Estatísticas oficiais do mercado de trabalho europeu (EURES) |
| `GET` | `/api/profile` | Retorna metadados e termos de busca dinâmicos do perfil do usuário |
| `POST` | `/api/search` | Dispara busca em segundo plano nos portais configurados |
| `POST` | `/api/batch-screen` | Dispara triagem em lote assíncrona das vagas selecionadas |
| `POST` | `/api/mark` | Marca vaga como "Me interessa" ou "Descartar" |
| `POST` | `/api/clear-pending` | Limpa em lote vagas pendentes não salvas |
