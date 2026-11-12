<p align="center">
  <img src="assets/mascot/pip_flight_loop.gif" alt="Pip, o passarinho mensageiro" width="160">
</p>

# Vagamundo

*A sua plataforma inteligente de busca de emprego e aceleração de carreira — rodando 100% na sua máquina.*

O **Vagamundo** é um ecossistema completo e local para profissionais buscarem vagas, avaliarem compatibilidade com Inteligência Artificial, gerarem currículos e cartas sob medida e acompanharem todo o pipeline de candidaturas e evolução técnica.

---

## Principais Funcionalidades

### 1. Busca Multicanal em 24 Portais de Vagas
O Vagamundo agrega oportunidades de 24 portais nacionais e internacionais em uma interface unificada:
- **Portais ATS Corporativos:** Gupy, Sólides Vagas, Greenhouse, Ashby e DigAÍ (entrevistas por IA).
- **Portais Especializados em Tecnologia e Comunicação:** Programathor, GeekHunter, Trampos, FreeHire (agregador técnico global), Habr Career e Hacker News.
- **Portais Generalistas, Executivos e Internacionais:** VAGAS.com, InfoJobs Brasil, Empregos.com.br, Michael Page, Robert Half, LinkedIn e HeadHunter (`hh.ru`).
- **Vagas 100% Remotas:** Remotar (Brasil), Jobicy e RemoteOK (Internacionais).
- **Vagas Afirmativas & Nichos:** PCD Online (exclusivo para PcD), Agrobase e AGROSearch (agronegócio e ciências agrárias).

### 2. Mapa Interativo (Brasil & Mundo)
- Visualização cartográfica interativa da distribuição de vagas por estado brasileiro (27 UFs) e por país (172 nações).
- Identificação instantânea de pólos de contratação e filtros rápidos para vagas 100% remotas nacionais ou internacionais.

### 3. Inteligência Artificial Multi-Provedor
- Suporte nativo e configurável a **Google Gemini**, **Anthropic Claude** e **OpenAI** (com compatibilidade para modelos locais via **Ollama**).
- **Triagem Rápida & Fit Score:** Avaliação automatizada de aderência (0 a 100) cruzando os requisitos de cada vaga com suas experiências e formação reais.
- **Detecção de Fraudes e Golpes:** Identificação em tempo real de anúncios suspeitos (pedidos de Pix, dados bancários ou canais ilegítimos).

### 4. Geração Sob Medida de Currículos e Cartas
- Geração instantânea de **Cartas de Apresentação** persuasivas e personalizadas para a empresa e o cargo.
- Adaptação de **Currículos Técnicos** em LaTeX (com compilação automática para PDF) destacando as competências exigidas pela vaga.

### 5. Dossiê Preparatório para Entrevistas
- Simulação de perguntas técnicas prováveis baseadas na stack da vaga.
- Questões comportamentais e preparação de respostas no método STAR.
- Perguntas estratégicas sugeridas para o candidato fazer ao recrutador ou gestor técnico.

### 6. Pipeline de Candidaturas & Evolução Profissional
- Acompanhamento do ciclo de vida das candidaturas (Interesse, Aplicada, Entrevista, Aprovada, Rejeitada).
- **Aba de Evolução:** Mapeamento de competências demandadas pelas vagas monitoradas e sugestões de capacitação técnica (*upskilling*).

---

## Arquitetura do Sistema

```
vagamundo/
├── frontend/             # SPA Angular 17+ (Signals, Standalone Components, Design Dark)
├── backend/
│   ├── api/              # API Gateway FastAPI assíncrona (rotas REST, schemas Pydantic)
│   ├── core/             # Serviços de negócio (avaliador, rastreador, perfil)
│   ├── db/               # SQLite primário (modo WAL) e repositório de persistência
│   └── tools/            # Utilitários de compilação, scraping e integração com IA
├── .agents/skills/       # 24 Scrapers de portais de vagas em TypeScript (Bun)
└── docs/                 # Documentação arquitetural detalhada e ADRs
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

# Instale as dependências do Python
pip install -r requirements.txt

# Instale as dependências do Frontend e dos Portais
npm run install:all
```

### 2. Configurar a Chave de Inteligência Artificial
Copie o `.env.example` para `.env` e preencha sua chave (o **Google Gemini** possui plano gratuito):
```bash
cp .env.example .env
```
No arquivo `.env`:
```env
AI_PROVIDER=gemini
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

Para instruções detalhadas de configuração, consulte o [SETUP.md](SETUP.md).

---

## Privacidade e Segurança (Local-First)

- **Seus dados pertencem a você:** Seu currículo, histórico de candidaturas e banco de dados SQLite (`data/vagamundo.db`) residem unicamente no seu disco rígido e nunca são enviados para servidores externos não autorizados.
- **Chaves de API protegidas:** O arquivo `.env` é estritamente ignorado pelo Git.
- Para detalhes, consulte [DATA_CONTRACT.md](DATA_CONTRACT.md) e [SECURITY.md](SECURITY.md).
