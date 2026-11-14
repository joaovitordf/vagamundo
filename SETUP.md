# Guia de Instalação e Execução — Vagamundo

Este guia contém o passo a passo completo e atualizado para clonar, configurar e executar o **Vagamundo** em qualquer máquina (Windows, Linux ou macOS).

---

## 1. Visão Geral da Arquitetura

O Vagamundo é composto por:
- **Frontend SPA:** Angular 17+ moderno com interface reativa em `http://localhost:4200`.
- **Backend API Gateway:** FastAPI assíncrono com Uvicorn rodando em `http://127.0.0.1:8765`.
- **Banco de Dados:** SQLite local (`data/vagamundo.db`) com modo WAL e criação automática de tabelas.
- **Portais de Vagas:** 24 ferramentas de scraping em TypeScript executadas via Bun (`.agents/skills/`).
- **Motor de Inteligência Artificial:** Integração configurável com Google Gemini, Anthropic Claude ou OpenAI.

---

## 2. Pré-requisitos

Antes de iniciar, certifique-se de ter instalado em sua máquina:

1. **Python 3.10 ou superior** (Recomendado: Python 3.12)
   - Verifique com: `python --version` (ou `python3 --version`).
   - *Windows:* Certifique-se de marcar "Add Python to PATH" durante a instalação.

2. **Node.js (versão 18+ ou 20+) e npm**
   - Verifique com: `node --version` e `npm --version`.
   - Download: [nodejs.org](https://nodejs.org/)

3. **Bun** (Essencial para as ferramentas de busca de vagas em TypeScript)
   - *Windows (via winget):*
     ```powershell
     winget install Oven-sh.Bun
     ```
   - *Windows (via PowerShell sem winget):*
     ```powershell
     powershell -ExecutionPolicy Bypass -c "irm https://bun.sh/install.ps1 | iex"
     ```
   - *Linux / macOS:*
     ```bash
     curl -fsSL https://bun.sh/install | bash
     ```
   - Verifique com: `bun --version`. *(Dica: feche e reabra o terminal após instalar).*

4. *(Opcional)* **Compilador LaTeX** (Apenas se quiser gerar arquivos PDF de currículos e cartas)
   - *Windows:* [MiKTeX](https://miktex.org/download) ou `winget install MiKTeX.MiKTeX`
   - *Linux:* `sudo apt install texlive-full`
   - *macOS:* [MacTeX](https://tug.org/mactex/)
   - *Nota:* Sem o LaTeX, o sistema ainda funciona 100%, gerando os textos e códigos-fonte `.tex` e `.md` de todas as vagas, currículos e cartas.

---

## 3. Instalação Passo a Passo

### Passo 1: Clonar o Repositório

> **Aviso de Privacidade:** Um **fork público** (`gh repo fork`) expõe qualquer commit feito nele; se for manter um backup próprio no GitHub, use um **repositório privado**, pois o `/setup` preenche **dados pessoais** no perfil local. Veja as regras completas em [SECURITY.md](SECURITY.md).

```bash
git clone https://github.com/joaovitordf/vagamundo.git
cd vagamundo
```

### Passo 2: Ambiente Virtual Python *(Opcional, mas recomendado)*
Se desejar isolar as dependências Python em `.venv` (o `npm run install:all` e o `npm run dev` detectam a `.venv` automaticamente mesmo sem ativá-la no terminal):

- **No Windows:**
  ```powershell
  python -m venv .venv
  ```
- **No Linux/macOS:**
  ```bash
  python3 -m venv .venv
  ```

### Passo 3: Instalar Tudo com Um Comando
Na raiz do projeto, execute:
```bash
npm run install:all
```
Esse comando instala automaticamente:
1. As dependências Python do backend (`requirements.txt`).
2. As dependências do frontend Angular (`frontend/`).
3. Todas as **24 CLIs de portais de vagas** sob `.agents/skills/` (para reinstalar só os portais, use `npm run install:portals`).

### Passo 4: Configurar as Chaves de IA (`.env`) — *Opcional*
Você não precisa criar nenhum arquivo manual se preferir cadastrar sua chave direto pela interface web (aba **Configurações**, que grava localmente no `.env` da raiz — nunca versionado).

Se preferir configurar via arquivo, crie **1 único `.env` na raiz** a partir de `.env.example` (o caminho legado `backend/.env` continua lido como fallback caso já exista):

```bash
# Windows (PowerShell):
copy .env.example .env

# Linux / macOS:
cp .env.example .env
```

Abra o arquivo `.env` gerado e preencha sua chave (`AI_PROVIDER=auto` detecta automaticamente a primeira chave preenchida):
```env
AI_PROVIDER=auto
AI_DATA_CONSENT=yes
GEMINI_API_KEY=sua_chave_do_google_ai_studio_aqui
```
> **Dica:** A chave do **Google Gemini** é gratuita e pode ser gerada instantaneamente em [aistudio.google.com](https://aistudio.google.com/app/apikey).
> Você também pode optar por usar **Anthropic Claude**, **OpenAI** ou **Ollama** (local).

---

## 4. Executando o Projeto

Para iniciar o ecossistema completo com um único comando:

```bash
npm run dev
```

O comando irá:
1. Detectar `.venv` automaticamente (ou o Python do sistema).
2. Liberar portas residuais em Windows, Linux e macOS (`8765` e `4200`).
3. Iniciar o servidor FastAPI com Uvicorn na porta `8765`.
4. Iniciar o servidor de desenvolvimento do Angular na porta `4200`.

### Acesso:
- **Interface Web:** [http://localhost:4200](http://localhost:4200)
- **Documentação da API (Swagger):** [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs)

Para encerrar a aplicação, pressione `Ctrl + C` no terminal.

---

## 5. Personalizando o Seu Perfil *(0 arquivos versionados editados)*

O Vagamundo personaliza notas de triagem, currículos, cartas e dossiês com base no seu perfil real, **sem editar nenhum arquivo rastreado pelo Git**:
1. Acesse a aba **"Meu Perfil"** na interface web (`http://localhost:4200`).
2. Faça o upload do seu currículo (PDF/DOCX/TXT) ou perfil do LinkedIn (salvo localmente em `backend/documents/perfil/`, já no `.gitignore`).
3. Preencha suas preferências (cargo-alvo, senioridade, cidades, modelo de trabalho) e clique em **Gerar perfil com IA** (opcional — mesmo sem clicar, o formulário e os CVs enviados já alimentam a triagem e o `Sortear área CV`).
4. **Uso avançado (opcional):** quem utiliza agentes de terminal (Claude Code / Antigravity slash commands) pode opcionalmente manter `CLAUDE.md`, `.claude/skills/job-application-assistant/01-candidate-profile.md` e `.claude/skills/job-scraper/search-queries.md`.

---

## 6. Solução de Problemas Comuns (Troubleshooting)

- **`bun` não é reconhecido como comando interno:**
  - Após instalar o Bun, feche todas as janelas do terminal e do VS Code e abra novamente para atualizar a variável `PATH` do sistema.
- **Erro de permissão no PowerShell (`script não pode ser carregado`):**
  - Execute no PowerShell como usuário:
    ```powershell
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    ```
- **Porta em uso (EADDRINUSE):**
  - O script `npm run dev` (`dev.js`) encerra processos nas portas `8765` e `4200` automaticamente. Caso precise forçar manualmente:
    ```powershell
    # Windows:
    npx kill-port 8765 4200
    ```
- **Erro de SQLite ou banco inexistente:**
  - O banco de dados `data/vagamundo.db` é criado e inicializado automaticamente com todas as tabelas na primeira execução do backend.
