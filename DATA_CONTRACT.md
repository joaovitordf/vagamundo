# Contrato de Dados (Data Contract) — Vagamundo v2

Este documento formaliza as fronteiras entre os componentes do sistema (**System Layer**) e os dados pessoais do candidato (**User Layer**), garantindo atualizações seguras e integridade estrutural.

---

## 1. Camadas Arquiteturais

### Camada do Sistema (System Layer) — *Rastreada pelo Git / Atualizável*
Contém o código-fonte, templates canônicos, especificações e contratos de execução:

| Caminho | Descrição | Dono |
| :--- | :--- | :--- |
| `.agents/skills/` | Ferramentas de busca de vagas em portais (TypeScript/Bun) | Sistema |
| `.agents/skills/_portal-kit/` | Pacote compartilhado de utilitários de scraping e CLI | Sistema |
| `.claude/skills/` e `.claude/commands/` | Fluxos canônicos e instruções de agentes (Antigravity/Codex/Claude) | Sistema |
| `backend/api/` | Gateway HTTP assíncrono em FastAPI | Sistema |
| `backend/core/` | Serviços do domínio de negócio (scanner, evaluator, docgen, liveness, tracker) | Sistema |
| `backend/db/` | Schema SQL (`schema.sql`) e Repository de persistência SQLite | Sistema |
| `backend/tools/` | Utilitários de CLI invocados pelos agentes e rotinas de compilação | Sistema |
| `frontend/` | SPA Angular moderna para interface gráfica local | Sistema |
| `docs/adr/` | Decisões arquiteturais registradas | Sistema |

### Camada do Usuário (User Layer) — *Protegida / Pessoal / Ignorada pelo Git*
Contém as preferências, credenciais, histórico de buscas, dados cadastrais e documentos do candidato:

| Caminho | Descrição | Tratamento |
| :--- | :--- | :--- |
| `data/vagamundo.db*` | Banco de dados local primário SQLite (WAL mode) | Gitignored |
| `.env` | Chaves de API de provedores de IA (OpenAI, Gemini, Anthropic) na raiz (editadas na aba Configurações ou manualmente; fallback legado em `backend/.env`) | Gitignored |
| `backend/documents/perfil/` | Perfil e respostas estruturadas pela Web UI (`respostas.json`, `candidate-profile.md`, `search-queries.md`) | Gitignored |
| `backend/documents/cv/` e `backend/documents/linkedin/` | Uploads locais da pessoa candidata (currículos e exportação LinkedIn) | Gitignored |
| `backend/documents/applications/` e `backend/documents/interview/` | Dossiês de candidatura, cartas arquivadas e pacotes de entrevista | Gitignored |
| `backend/cv/` e `backend/cover_letters/` | PDFs e arquivos `.tex` personalizados compilados por vaga (além de `main_example.tex` / `cover_example.tex`) | Gitignored (exceto exemplos) |

---

## 2. Princípios de Governança de Dados

1. **Persistência Atômica:** Qualquer mutação em lote de vagas, candidaturas ou avaliações é executada dentro de transações SQLite atômicas com modo WAL.
2. **Privacidade Estrita:** Nenhuma chave de API, CPF, RG ou dado sensível é incluído no controle de versão ou enviado sem consentimento explícito.
3. **Ponteiro Único de IA:** Os arquivos sob `.claude/skills/` e `.claude/commands/` permanecem a fonte única de verdade dos fluxos de trabalho assistidos por IA.

