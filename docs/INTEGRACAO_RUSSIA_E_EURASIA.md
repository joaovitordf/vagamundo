# Integração da Rússia e Eurásia (HeadHunter e Habr Career)

## 1. Visão Geral

Este documento detalha a expansão das capacidades de busca internacional do **Vagamundo** para o mercado da **Rússia e Eurásia**, por meio de duas plataformas técnicas integradas como **Agent Skills** portáteis em `.agents/skills/`:

1. **HeadHunter (`hh-search`):** Maior portal corporativo e de tecnologia da Rússia e Leste Europeu.
2. **Habr Career (`habrcareer-search`):** Portal especializado da comunidade técnica Habr.

Ambas são executadas via **Bun** (`cli/src/cli.ts`), autorizadas na allowlist de `.claude/settings.json` e `backend/tools/security_guards.py`, e mapeadas para o portal `hh-search` e `habrcareer-search` no painel Angular.

---

## 2. Portais Integrados

### 2.1 HeadHunter (`hh-search`)
- **Pasta:** `.agents/skills/hh-search/`
- **Foco:** Vagas de tecnologia, engenharia de software, dados, infraestrutura e posições corporativas (incluindo posições remotas internacionais e ofertas com realocação).
- **Estratégia Técnica:**
  - Como `api.hh.ru` restringe buscas públicas sem OAuth/IP local, a skill consulta as rotas web públicas (`https://hh.ru/search/vacancy` e `https://hh.ru/vacancy/<id>`).
  - Extrai título, empresa, localidade, faixa salarial, modelo de trabalho e descrição.

### 2.2 Habr Career (`habrcareer-search`)
- **Pasta:** `.agents/skills/habrcareer-search/`
- **Foco:** Comunidade técnica especializada (desenvolvimento, DevOps, IA/ML, QA, liderança técnica).
- **Estratégia Técnica:**
  - Consulta as listagens públicas em `https://career.habr.ru/vacancies` com suporte a busca (`q`), filtros técnicos e trabalho remoto (`remote=1`).

---

## 3. Engenharia de Palavras-Chave e Cirílico

### 3.1 Abordagem Híbrida (Inglês vs. Cirílico)
Os motores de busca locais respondem bem à combinação de tecnologias em inglês com papéis profissionais em cirílico ou inglês:

| Nomenclatura em Inglês | Título Híbrido Frequente (Cirílico) | Sinônimo Técnico |
| :--- | :--- | :--- |
| `Python Developer` | `Python разработчик` | `Программист Python` |
| `Frontend Engineer` | `Frontend разработчик` | `React / Vue инженер` |
| `Data Scientist` | `Специалист по Data Science` | `Инженер данных` |
| `DevOps Engineer` | `DevOps инженер` | `SRE / Системный инженер` |
| `Machine Learning` | `ML разработчик` | `Инженер машинного обучения` |

### 3.2 Modelos de Trabalho e Senioridade
- **Remoto:** `Удалённая работа` / `Удаленка` (`schedule=remote`).
- **Híbrido:** `Гибридный график` (`schedule=hybrid`).
- **Relocation / Visto:** `Релокация` / `Помощь с переездом`.
- **Senioridade:** Стажёр / Junior, Middle, Senior, Lead / Team Lead.

---

## 4. Integração com o Painel e Mapa Mundial

1. **Seletor de Fontes (`job-filters.util.ts`):**
   - Listadas sob **Internacional & Remoto Global** (parte dos **24 portais** integrados no dropdown da aba **Buscar e Vagas**).
2. **Resolução Geográfica (`resolveGeo`):**
   - Mapeia termos como `Rússia`, `Russia`, `Moscou`, `Moscow`, `São Petersburgo`, `Saint Petersburg` e os identificadores dos portais para o código ISO-2 **`RU`** no mapa mundial SVG.

---

## 5. Auditoria de Segurança (NVIDIA SkillSpector)

Na auditoria estática com **NVIDIA SkillSpector (`--no-llm`)**, ambas as skills (`hh-search` e `habrcareer-search`) apresentam:
- **Risco:** `26/100` (**MEDIUM / CAUTION**).
- **Causa dos alertas:** Exclusivamente recomendações genéricas de hardening presentes no conjunto das CLIs (`SC1` dependências com faixa `^`/`~` em `cli/package.json` e `LP1` acesso a rede esperado da própria CLI em `cli/src/` e `tests/`).
- **Zero exfiltração (`E1`) e zero prompt injection.** Para contexto completo das auditorias, veja [Segurança, Whitelabel e Privacidade Pré-Push](SEGURANCA_E_WHITELABEL.md).
