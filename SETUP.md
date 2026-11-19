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

O Vagamundo personaliza notas de triagem, currículos, cartas e dossiês para qualquer área profissional com base no seu perfil real, **sem editar nenhum arquivo rastreado pelo Git**:

1. Acesse a aba **"Meu Perfil"** na interface web (`http://localhost:4200/meu-perfil`).
2. **Envio de documentos (estritamente `.pdf` na interface web):**
   - Clique em **"Enviar currículo (PDF)"** para salvar seu currículo em `backend/documents/cv/`.
   - Clique em **"Enviar LinkedIn (PDF)"** para salvar a exportação em PDF do seu perfil do LinkedIn em `backend/documents/linkedin/`.
   - *(Ambos os diretórios estão protegidos no `.gitignore`.)*
3. **Extração e preenchimento do formulário:**
   - Ao enviar um PDF (ou clicando manualmente no botão **"Organizar tudo do PDF com a IA"**), a IA extrai seus dados objetivos, preenche o formulário e gera os arquivos locais em `backend/documents/perfil/`:
     - `respostas.json` — respostas estruturadas do formulário (cargos, palavras-chave do sorteio, senioridade, cidades, modelo de trabalho, regimes e deal-breakers).
     - `search-queries.md` — consultas de busca geradas automaticamente a partir das suas respostas.
     - `candidate-profile.md` — perfil consolidado em Markdown usado pela triagem e geração de documentos.
   - **Sem PDF ou sem IA configurada?** Você pode preencher o formulário diretamente e clicar em **"Salvar respostas"** — o sistema já gera `respostas.json` e `search-queries.md` em `backend/documents/perfil/`, habilitando imediatamente as buscas e o botão **"Sortear área CV"**.
4. **Consolidação manual com IA:**
   - Sempre que ajustar respostas ou anexar novos PDFs, você pode clicar em **"Montar meu perfil com a IA"** (ou **"Atualizar meu perfil com a IA"**) para regenerar `backend/documents/perfil/candidate-profile.md`.
5. **Uso avançado por agentes de terminal (opcional):**
   - Quem utiliza slash commands no Claude Code / Antigravity (`/setup`, `/scrape`, `/apply`) também pode manter os arquivos canônicos `CLAUDE.md`, `.claude/skills/job-application-assistant/01-candidate-profile.md` e `.claude/skills/job-scraper/search-queries.md` protegidos com `skip-worktree` (veja a **Seção 8** abaixo).

---

## 6. Fluxos Principais do Painel Web

Com o perfil pronto e o servidor rodando em `http://localhost:4200`:

1. **Buscar e Vagas (`/buscar-vagas`):**
   - Pesquise em até **24 portais nacionais e internacionais** simultaneamente, use o botão **"Sortear área CV"**, filtre por região/modelo de trabalho e alterne entre a grade de **Cards** e o **Mapa Mundial / Brasil em SVG**.
2. **Radar de Recrutadores (`/recrutadores`):**
   - Minera publicações com contato direto (`@`) em feeds públicos e portais ao vivo.
   - Inclui a **Barra de Pesquisa LinkedIn** (com sorteio automático de área do CV, expansão bilíngue PT↔EN + variação por IA, presets enxutos como *Vagas*, *Hiring + E-mail*, *E-mail / CV* e *Só termos*, link fallback para **Google X-Ray** e caixa de colagem com avaliação inline da IA e botões **"Me interessa"** e **"Descartar"**).
3. **Modo Automático Contínuo:**
   - Disponível tanto em **Buscar e Vagas** quanto em **Recrutadores**, sorteando áreas do currículo em background com intervalo anti-ban, detecção de rate-limit e promoção automática das vagas com nota compatível para **Me Interessam** (`/me-interessam`).
4. **Geração de Materiais e Pipeline (`/me-interessam` e `/candidaturas`):**
   - Gere currículos adaptados em LaTeX/PDF (`lualatex`), cartas de apresentação (`xelatex`) e dossiês de entrevista, acompanhando todas as etapas do processo seletivo.

---

## 7. Solução de Problemas (Troubleshooting)

- **`bun` não é reconhecido como comando interno:**
  - Após instalar o Bun, feche todas as janelas do terminal e do VS Code e abra novamente para atualizar a variável `PATH` do sistema.
- **`npm run backend` ou `uvicorn` fora da `.venv`:**
  - Os comandos `npm run dev`, `npm run backend` e `npm run install:all` localizam automaticamente `.venv/Scripts/python.exe` (Windows) ou `.venv/bin/python` (Linux/macOS), sem exigir ativação manual do ambiente virtual.
- **Erro de permissão no PowerShell (`script não pode ser carregado`):**
  - Execute no PowerShell como usuário:
    ```powershell
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    ```
- **Porta em uso (`EADDRINUSE` nas portas `8765` ou `4200`):**
  - O script `npm run dev` (`dev.js`) encerra automaticamente processos órfãos nas portas `8765` e `4200` em Windows (`netstat`/`taskkill`) e Linux/macOS (`lsof`/`fuser`). Caso precise liberar manualmente:
    ```bash
    npx kill-port 8765 4200
    ```
- **Upload recusado na aba Meu Perfil:**
  - A interface web aceita exclusivamente arquivos **`.pdf`** (até 10 MB). Se o seu currículo estiver em Word (`.docx`), exporte-o como PDF antes de enviar.
- **Erro de SQLite ou banco inexistente:**
  - O banco de dados `data/vagamundo.db` é criado e migrado automaticamente em modo WAL na primeira execução do backend.

---

## 8. Privacidade, `skip-worktree` e Atualizações (`git pull`)

O Vagamundo foi projetado com arquitetura **Local-First & Whitelabel** para que seus dados pessoais nunca vazem em um repositório público:

### 8.1 Onde ficam seus dados locais (100% no `.gitignore`)
Quando você usa o painel web, **nenhum arquivo rastreado pelo Git é modificado**:
- Chaves de API ficam apenas no `.env` da raiz.
- PDFs enviados ficam em `backend/documents/cv/` e `backend/documents/linkedin/`.
- Formulário e perfil gerado ficam em `backend/documents/perfil/` (`respostas.json`, `search-queries.md`, `candidate-profile.md`).
- Vagas, avaliações e candidaturas ficam em `data/vagamundo.db`.

### 8.2 Receita de 2 minutos para Repositório Privado (evite Forks Públicos)
Um **fork de repositório público no GitHub é sempre público**. Se você pretende rodar o comando `/setup` no terminal (que preenche arquivos como `CLAUDE.md` e `.claude/skills/...`) e quer salvar backup na nuvem, aponte seu `origin` para um **repositório privado**:

```bash
# 1. Crie um repositório privado vazio na sua conta (via GitHub CLI ou interface web):
gh repo create meu-vagamundo-privado --private

# 2. Renomeie o repositório original para 'upstream' e aponte 'origin' para o seu repo privado:
git remote rename origin upstream
git remote add origin https://github.com/<seu-usuario>/meu-vagamundo-privado.git
git push -u origin main
```

### 8.3 Protegendo arquivos de template com `skip-worktree`
Se você personalizou os arquivos canônicos pelo comando `/setup` (`CLAUDE.md`, `.claude/skills/job-application-assistant/01-candidate-profile.md`, `.claude/skills/job-scraper/search-queries.md`, `backend/cv/main_example.tex`), proteja-os no Git local para que `git status` e `git commit -a` ignorem suas alterações pessoais:

```bash
git update-index --skip-worktree CLAUDE.md \
  .claude/skills/job-application-assistant/01-candidate-profile.md \
  .claude/skills/job-scraper/search-queries.md \
  backend/cv/main_example.tex
```

### 8.4 Como atualizar o projeto (`git pull`) com `skip-worktree` ativo
Ao puxar atualizações do repositório oficial (`git pull upstream main` ou `git pull`), caso algum arquivo marcado com `skip-worktree` tenha recebido melhorias estruturais no template:

```bash
# 1. Destrave temporariamente os arquivos marcados:
git update-index --no-skip-worktree CLAUDE.md \
  .claude/skills/job-application-assistant/01-candidate-profile.md \
  .claude/skills/job-scraper/search-queries.md \
  backend/cv/main_example.tex

# 2. Guarde suas alterações locais, puxe a atualização e reaplique:
git stash push -m "meu-perfil-local"
git pull --rebase
git stash pop

# 3. Reative o skip-worktree:
git update-index --skip-worktree CLAUDE.md \
  .claude/skills/job-application-assistant/01-candidate-profile.md \
  .claude/skills/job-scraper/search-queries.md \
  backend/cv/main_example.tex
```

### 8.5 Auditoria Pré-Push (`check_privacy.py`)
Antes de qualquer `git push`, execute o verificador automático de privacidade:

```bash
python backend/tools/check_privacy.py
```

Ele inspeciona arquivos rastreados, novos arquivos não ignorados, *staging area*, `HEAD` de arquivos com `skip-worktree` e regras do `.gitignore`, bloqueando o envio caso detecte chaves de API, CPF/CNPJ ou dados do seu perfil local.
