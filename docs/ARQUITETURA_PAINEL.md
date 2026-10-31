# Arquitetura do Painel Web Local (Vagamundo v2)

## 1. Princípios Arquiteturais

O painel de controle do **Vagamundo** opera como uma aplicação local fullstack moderna, dividida em camadas bem definidas e desacopladas:

1. **Frontend SPA (Angular 17+):**
   - Construído com TypeScript, componentes standalone e Angular Signals para reatividade de alto desempenho.
   - Comunicação transparente com o backend através de proxy local (`proxy.conf.json`) apontando para `http://127.0.0.1:8765`.
   - Interface com design dark moderno, mapas interativos em SVG/Canvas e renderização instantânea com cache inteligente.

2. **Backend API Gateway (FastAPI + Uvicorn):**
   - API REST assíncrona modularizada sob `backend/api/` (`routes/`, `models.py`, `deps.py`).
   - Documentação interativa automática OpenAPI disponível em `http://127.0.0.1:8765/docs`.
   - Gerenciamento de tarefas em segundo plano (background tasks) para scraping paralelo e chamadas de IA.

3. **Camada de Persistência Primária (SQLite com WAL Mode):**
   - Banco de dados relacional local `data/vagamundo.db` com transações ACID, integridade referencial e modo WAL (*Write-Ahead Logging*).
   - Inicialização e migração de schema automáticas a partir de `backend/db/schema.sql`.

4. **Gateway de Inteligência Artificial Multi-Provedor:**
   - Suporte unificado para Google Gemini, Anthropic Claude e OpenAI (com compatibilidade para Ollama local).
   - Pipeline de triagem rápida, notas de aderência (fit scoring), dossiês preparatórios para entrevistas e geração de currículos/cartas sob medida.

---

## 2. Estrutura de Abas da Interface

1. **Buscar Vagas:**
   - Console de filtros avançados por cargo, modalidade (remoto, híbrido, presencial), regime (CLT, PJ, estágio) e intervalo de publicação (`jobage`).
   - Visualização alternável entre **Cards de Vagas** e **Mapa Mundial / Brasil** interativo com distribuição geográfica de oportunidades.
   - Ações de triagem rápida com IA e classificação de afinidade.
2. **Vagas que me interessam:**
   - Hub de vagas marcadas com estrela para acompanhamento aprofundado.
   - Ações de geração instantânea de **Carta de Apresentação**, **Currículo Adaptado** e **Dossiê de Entrevista com IA**.
3. **Candidaturas:**
   - Tabela de gestão de pipeline com status (aplicada, em processo, entrevista, aprovada, rejeitada).
   - Acesso direto a materiais gerados e modal de histórico detalhado.
4. **Evolução Profissional:**
   - Análise de tendências de mercado, lacunas de competências identificadas e roadmap de capacitação (*upskilling*).
5. **Currículos e Cartas:**
   - Histórico e download dos documentos compilados em PDF e fontes LaTeX.
6. **Descartadas:**
   - Repositório de vagas descartadas com filtro e restauração em um clique.
7. **Meu Perfil:**
   - Visualização e edição do perfil profissional, histórico e upload de currículo base.
8. **Configurações:**
   - Seleção visual do provedor de IA ativo e teste de conectividade.

---

## 3. Inicialização Unificada

O ecossistema é gerenciado de forma automatizada pelo script `dev.js`:

```bash
npm run dev
```

- Libera as portas `8765` e `4200` caso tenham processos órfãos.
- Inicia o servidor backend FastAPI com Uvicorn.
- Aguarda a prontidão da API e inicia o servidor de desenvolvimento do Angular.
- Abre o fluxo completo na porta `http://localhost:4200/`.
