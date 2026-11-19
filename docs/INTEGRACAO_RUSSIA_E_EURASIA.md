# Integração da Rússia e Eurásia (HeadHunter e Habr Career)

## 1. Visão Geral

Este documento detalha a expansão das capacidades de busca internacional do **Vagamundo** para o mercado da **Rússia e Eurásia**, por meio de duas plataformas técnicas integradas como **Agent Skills** portáteis em `.agents/skills/`:

1. **HeadHunter (`hh-search`):** Maior portal corporativo e de tecnologia da Rússia e Leste Europeu.
2. **Habr Career (`habrcareer-search`):** Portal especializado da comunidade técnica Habr.

Ambas são executadas via **Bun** (`cli/src/cli.ts`), autorizadas na allowlist de `.claude/settings.json` e `backend/tools/security_guards.py`, e mapeadas para o portal `hh-search` e `habrcareer-search` no painel Angular.

---

## 2. Portais Integrados e Decisões de Arquitetura

### 2.1 HeadHunter (`hh-search`)
- **Pasta:** `.agents/skills/hh-search/`
- **Foco:** Vagas de tecnologia, engenharia de software, dados, infraestrutura e posições corporativas (incluindo posições remotas internacionais e ofertas com realocação).
- **Estratégia Técnica:**
  - Como `api.hh.ru` restringe buscas públicas sem OAuth/IP local, a skill consulta as rotas web públicas (`https://hh.ru/search/vacancy` e `https://hh.ru/vacancy/<id>`).
  - **Janela de Extração de Cards (14.000 chars):** O HTML SSR do `hh.ru` incorpora blocos extensos de telemetria e estilos inline antes dos metadados de empresa, cidade e senioridade; por isso, o parser utiliza uma janela de **14.000 caracteres** por card (`vacancy-serp-item` / `serp-item`) para extrair com precisão `company`, `location`, faixa salarial, senioridade e modelo de trabalho.

### 2.2 Habr Career (`habrcareer-search`)
- **Pasta:** `.agents/skills/habrcareer-search/`
- **Foco:** Comunidade técnica especializada (desenvolvimento, DevOps, IA/ML, QA, liderança técnica).
- **Estratégia Técnica:**
  - **Domínio migrado para `career.habr.com`:** O antigo domínio `career.habr.ru` redireciona para `https://career.habr.com/vacancies`; a CLI opera diretamente sobre `career.habr.com`.
  - **Extração via SSR JSON (`<script data-ssr-state="true">`):** Em vez de depender de seletores HTML frágeis na listagem, a CLI faz o parse do payload JSON hidratado pelo servidor em `<script data-ssr-state="true">`, extraindo estruturadamente `id`, `title`, `company`, `salary`, `remoteWork`, `divisions`, `skills` e `publishedDate`, com fallback para HTML quando necessário.
  - **Filtro Remoto (`remote=1`):** Suporta filtragem nativa de vagas 100% remotas via parâmetro `remote=1` (acionado por `--remote`), além de paginação e busca por termos (`q`).

### 2.3 Por que o `superjob.ru` foi avaliado e descartado
Durante a expansão para o mercado da Rússia e Eurásia, o portal **SuperJob (`superjob.ru`)** foi avaliado tecnicamente e **descartado** por dois motivos impeditivos para uma arquitetura local-first/whitelabel:
1. **OAuth2 e `client_secret` obrigatórios:** A API oficial (`api.superjob.ru`) exige registro prévio de aplicativo com `client_secret` vinculado a conta e aprovação manual, inviabilizando execução *out-of-the-box* sem credenciais proprietárias.
2. **Certificado TLS doméstico russo (CA não confiável):** Os endpoints web do SuperJob utilizam cadeia de certificação doméstica russa (Russian Trusted Root CA) rejeitada por padrão pelos *trust stores* padrão do Node/Bun/Python/OpenSSL internacionais, o que exigiria desabilitar a verificação TLS (`rejectUnauthorized: false` / `verify=False`) — prática proibida pelas diretrizes de segurança do Vagamundo.

---

## 3. Tradução Automática PT→EN em `scrape_run.py` e Engenharia de Palavras-Chave

### 3.1 Tradução Automática de Consultas (`scrape_run.py`)
Tanto `hh.ru` quanto `career.habr.com` indexam vagas em **russo (cirílico)** e em **inglês** (especialmente para vagas técnicas e remotas internacionais), mas retornam **zero resultados** para títulos de cargos em português (ex.: `"Engenheiro de Software"`, `"Cientista de Dados"`, `"Desenvolvedor Backend"`).
- Para garantir resultados reais mesmo quando o perfil da pessoa candidata está todo em português, `backend/tools/scrape_run.py` traduz automaticamente os títulos e termos em português para seus equivalentes em inglês (`PT→EN`) antes de invocar `hh-search` e `habrcareer-search`.

### 3.2 Abordagem Híbrida (Inglês vs. Cirílico)
Os motores de busca locais respondem bem à combinação de tecnologias/cargos em inglês com papéis profissionais em cirílico ou inglês:

| Nomenclatura em Inglês | Título Híbrido Frequente (Cirílico) | Sinônimo Técnico |
| :--- | :--- | :--- |
| `Python Developer` | `Python разработчик` | `Программист Python` |
| `Frontend Engineer` | `Frontend разработчик` | `React / Vue инженер` |
| `Data Scientist` | `Специалист по Data Science` | `Инженер данных` |
| `DevOps Engineer` | `DevOps инженер` | `SRE / Системный инженер` |
| `Machine Learning` | `ML разработчик` | `Инженер машинного обучения` |

### 3.3 Modelos de Trabalho e Senioridade
- **Remoto:** `Удалённая работа` / `Удаленка` (`schedule=remote` no `hh-search` e `remote=1` no `habrcareer-search`).
- **Híbrido:** `Гибридный график` (`schedule=hybrid`).
- **Relocation / Visto:** `Релокация` / `Помощь с переездом`.
- **Senioridade:** Стажёр / Junior, Middle, Senior, Lead / Team Lead.

---

## 4. Integração com o Painel, Escopo Remoto e Mapa Mundial

1. **Seletor de Fontes e Escopo `REGION_PORTALS["remote"]` (`job-filters.util.ts` e `scanner.py`):**
   - Listadas sob **Internacional & Remoto Global** (parte dos **24 portais** integrados no dropdown da aba **Buscar e Vagas**).
   - Ambas as skills (`hh-search` e `habrcareer-search`) estão incluídas em `REGION_PORTALS["remote"]` (com flag `--remote`), garantindo que buscas por vagas 100% remotas globais também consultem oportunidades remotas na Eurásia.
2. **Resolução Geográfica (`resolveGeo`):**
   - Mapeia termos como `Rússia`, `Russia`, `Moscou`, `Moscow`, `São Petersburgo`, `Saint Petersburg` e os identificadores dos portais para o código ISO-2 **`RU`** no mapa mundial SVG (`GeoMapComponent`).

---

## 5. Auditoria de Segurança (NVIDIA SkillSpector)

Na auditoria estática com **NVIDIA SkillSpector (`--no-llm`)**, ambas as skills (`hh-search` e `habrcareer-search`) apresentam:
- **Risco:** `26/100` (**MEDIUM / CAUTION**).
- **Causa dos alertas:** Exclusivamente recomendações genéricas de hardening presentes no conjunto das CLIs (`SC1` dependências com faixa `^`/`~` em `cli/package.json` e `LP1` acesso a rede esperado da própria CLI em `cli/src/` e `tests/`).
- **Zero exfiltração (`E1`) e zero prompt injection.** Para contexto completo das auditorias, veja [Segurança, Whitelabel e Privacidade Pré-Push](SEGURANCA_E_WHITELABEL.md).
