<p align="center">
  <img src="assets/mascot/pip_flight_loop.gif" alt="Pip, o passarinho mensageiro" width="160">
</p>

# Vagamundo

*A sua plataforma inteligente de busca de emprego e aceleração de carreira — para qualquer profissão e mercado, rodando 100% na sua máquina.*

O **Vagamundo** é um ecossistema completo, *whitelabel* e local para profissionais de **qualquer área** (tecnologia, gestão, finanças, agronegócio, marketing, comunicação, engenharia, saúde, operações e mais) buscarem vagas no Brasil e no exterior, minerarem contatos diretos de recrutadores, avaliarem compatibilidade com Inteligência Artificial, gerarem currículos e cartas sob medida e acompanharem todo o pipeline de candidaturas e evolução profissional.

- **Guia completo de primeira instalação:** [SETUP.md](SETUP.md)
- **Documentação técnica e arquitetural:** [docs/README.md](docs/README.md)

---

## Principais Funcionalidades

### 1. Busca Multicanal em 24 Portais de Vagas
O Vagamundo agrega oportunidades de **24 portais nacionais e internacionais** (executados como Agent Skills via Bun em `.agents/skills/`) em uma interface unificada:
- **Portais ATS Corporativos:** Gupy (`gupy-search`), Sólides Vagas (`solides-search`), Greenhouse (`greenhouse-search`), Ashby (`ashby-search`) e DigAÍ (`digai-search`, entrevistas por IA).
- **Portais Generalistas, Executivos e Especialistas:** VAGAS.com (`vagas-search`), InfoJobs Brasil (`infojobs-search`), Empregos.com.br (`empregos-search`), Michael Page (`michaelpage-search`), Robert Half (`roberthalf-search`) e LinkedIn (`linkedin-search`).
- **Tecnologia, Produto, Design e Comunicação:** Programathor (`programathor-search`), GeekHunter (`geekhunter-search`), Trampos (`trampos-search`), FreeHire (`freehire-search`) e Hacker News *Who is Hiring* (`hn-search`).
- **Vagas 100% Remotas (Brasil e Exterior):** Remotar (`remotar-search`), Jobicy (`jobicy-search`) e RemoteOK (`remoteok-search`).
- **Rússia & Eurásia (com tradução automática PT→EN):** HeadHunter (`hh-search` em `hh.ru`) e Habr Career (`habrcareer-search` em `career.habr.com`), integrados ao escopo remoto global com tradução automática de termos de busca em português para inglês em `scrape_run.py`.
- **Vagas Afirmativas & Agronegócio:** PCD Online (`pcd-search`, exclusivo para PcD), Agrobase (`agrobase-search`) e AGROSearch (`agrosearch-search`).

### 2. Radar de Recrutadores & Barra de Pesquisa LinkedIn
- **Mineração de E-mails Diretos (`@`):** Consolida publicações com e-mail direto de recrutadores a partir de Hacker News, GitHub Vagas BR, Remotive, 9 portais CLI ao vivo e banco local, com higienização estrita, trecho contextual do contato e trava anti-duplicação via `application_ledger`.
- **Barra de Pesquisa LinkedIn (`LinkedinSearchBarComponent`):**
  - Sorteia automaticamente uma área do seu currículo ao abrir e monta queries booleanas enxutas (máx. 4 operadores para evitar bugs do feed do LinkedIn).
  - **Expansão Bilíngue (PT↔EN) + Variação por IA:** Combina dicionário bilíngue instantâneo para múltiplas profissões com expansão dinâmica via IA (`POST /api/recruiters/expand-search-term`).
  - **Presets prontos:** *Vagas*, *Hiring + E-mail*, *E-mail / CV* e *Só termos*, além de link fallback para **Google X-Ray**.
  - **Avaliação Inline por IA:** Ao colar posts do LinkedIn (com ou sem e-mail), a IA avalia imediatamente a aderência e exibe o card inline abaixo da caixa de colagem com botões **"Me interessa"** e **"Descartar"**.

### 3. Modo Automático Contínuo (Anti-Ban) e Verificação de Liveness
- **Loop Autônomo para Vagas e Recrutadores:** Sorteia áreas do currículo sem repetir termos recentes, varre os portais ou feeds de recrutadores, avalia com IA e promove automaticamente as oportunidades compatíveis para **Me Interessam** (`/me-interessam`).
- **Proteção Anti-Ban e Reversão:** Intervalo configurável com jitter, backoff automático ao detectar rate-limit (`429`), botão para pular espera (`skip-cooldown`) e reversão atômica (`undo`).
- **Verificação de Vagas Ativas (`Liveness Check`):** Sondagem assíncrona com proteção anti-SSRF e validação TLS (`POST /api/jobs/liveness`) para identificar anúncios encerrados ou expirados antes de investir tempo na candidatura.

### 4. Mapa Interativo (Brasil & Mundo)
- Visualização cartográfica interativa em SVG puro (`GeoMapComponent`) da distribuição de vagas por estado brasileiro (27 UFs) e por país (172 nações), sem dependências externas.
- Alternância entre modo **Volume de Vagas** e **Notas da Triagem IA**, com filtros rápidos para vagas remotas nacionais ou internacionais.

### 5. Inteligência Artificial Multi-Provedor
- Suporte nativo e configurável a **Google Gemini** (padrão `gemini-2.5-flash`), **Anthropic Claude** e **OpenAI** (com compatibilidade para modelos locais via **Ollama**).
- **Triagem Rápida & Fit Score:** Avaliação automatizada de aderência (0 a 100) cruzando os requisitos de cada vaga com suas experiências, senioridade, idiomas e formação reais.
- **Detecção de Fraudes e Golpes:** Identificação em tempo real de anúncios suspeitos (pedidos de Pix, pagamento antecipado ou dados bancários).

### 6. Geração Sob Medida de Currículos, Cartas e Dossiês de Entrevista
- Geração instantânea de **Cartas de Apresentação** (`xelatex`) persuasivas e personalizadas para a empresa e o cargo.
- Adaptação de **Currículos Profissionais** em LaTeX (`lualatex`, com compilação automática e segura para PDF) destacando as competências relevantes da sua trajetória.
- **Dossiê Preparatório para Entrevistas:** Perguntas técnicas/específicas da função, questões comportamentais no método STAR e perguntas estratégicas para fazer ao recrutador.
- **Pipeline de Candidaturas & Evolução:** Acompanhamento completo do funil (`/candidaturas`) e mapeamento de lacunas de competências (`/evolucao`).

---

## Arquitetura do Sistema

```
vagamundo/
├── frontend/             # SPA Angular 17+ (Signals, Standalone Components, Design Dark/Light)
├── backend/
│   ├── api/              # API Gateway FastAPI assíncrona (9 módulos de rotas REST, CSRF/HostCheck)
│   ├── core/             # Serviços de negócio (scanner, evaluator, tracker, auto_mode, recruiters/)
│   ├── db/               # SQLite primário (modo WAL) e repositórios modulares (*_repo.py)
│   └── tools/            # Utilitários de compilação LaTeX, scraping, privacidade e pacote ia/
├── .agents/skills/       # 24 Scrapers de portais de vagas em TypeScript (Bun)
└── docs/                 # Documentação arquitetural detalhada e ADRs (veja docs/README.md)
```

---

## Início Rápido (Quickstart)

### Pré-requisitos
- **Python 3.10+** (Recomendado 3.12)
- **Node.js 18+** e **npm**
- **Bun** ([instruções de instalação](https://bun.sh))

### 1. Clonar e Instalar Dependências

> **Aviso de Privacidade:** Prefira trabalhar em um **clone local** ou **repositório privado** (evite um *fork público* no GitHub via `gh repo fork`), pois comandos como `/setup` gravam seus **dados pessoais** em arquivos rastreados do perfil caso não estejam isolados. Consulte [SECURITY.md](SECURITY.md) antes de publicar alterações em um repositório remoto.

```bash
# Clone o repositório
git clone https://github.com/joaovitordf/vagamundo.git
cd vagamundo

# Instale dependências Python, Frontend e todos os 24 portais em um único comando
npm run install:all
```

> **Instalação limpa:** **0 arquivos versionados** precisam ser alterados após o clone. Todo perfil, upload de PDF (`backend/documents/cv/` e `backend/documents/linkedin/`) e geração de buscas (`backend/documents/perfil/`) funcionam direto pela interface web (já protegidos no `.gitignore`).

### 2. Configurar a Chave de Inteligência Artificial *(Opcional)*
Você pode cadastrar sua chave direto pela aba **Configurações** da interface web **ou**, se preferir usar arquivo, copiar `.env.example` para **1 único `.env` na raiz** (o **Google Gemini** possui plano gratuito):
```bash
cp .env.example .env
```
No arquivo `.env` (`AI_PROVIDER=auto` e `GEMINI_MODEL=gemini-2.5-flash` já vêm configurados como padrão):
```env
AI_PROVIDER=auto
AI_DATA_CONSENT=yes
GEMINI_API_KEY=sua_chave_do_google_ai_studio
```

### 3. Iniciar a Aplicação
```bash
npm run dev
```

Acesse a interface no navegador:
- **Painel Web:** [http://localhost:4200](http://localhost:4200)
- **API Swagger / Docs:** [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs)

Para instruções detalhadas de instalação, troubleshooting e configuração de repositório privado / `skip-worktree`, consulte o [SETUP.md](SETUP.md) e a documentação técnica em [docs/README.md](docs/README.md).

---

## Privacidade e Segurança (Local-First)

- **Seus dados pertencem a você:** Seu currículo, histórico de candidaturas e banco de dados SQLite (`data/vagamundo.db`) residem unicamente no seu disco rígido e nunca são enviados para servidores externos não autorizados.
- **Chaves de API protegidas:** O arquivo `.env` é estritamente ignorado pelo Git.
- Para detalhes, consulte [DATA_CONTRACT.md](DATA_CONTRACT.md) e [SECURITY.md](SECURITY.md).
