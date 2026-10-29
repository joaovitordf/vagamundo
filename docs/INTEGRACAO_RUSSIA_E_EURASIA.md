# Integração da Rússia e Eurásia (HeadHunter e Habr Career)

## 1. Visão Geral

Este documento detalha a expansão das capacidades de busca internacional do `vagamundo` para o mercado da **Rússia e Comunidade dos Estados Independentes (CEI/Eurásia)**, através da inclusão das duas maiores plataformas técnicas da região:

1. **HeadHunter (hh.ru):** Maior portal corporativo e de tecnologia do Leste Europeu.
2. **Habr Career (career.habr.ru):** Portal especializado da maior comunidade de desenvolvedores e engenharia da Rússia.

As duas integrações foram implementadas no padrão portátil **Agent Skills** (`.agents/skills/`), com execução via **Bun** e testes unitários automatizados em Python.

---

## 2. Portais Integrados

### 2.1 HeadHunter (`hh-search`)
- **Pasta:** `.agents/skills/hh-search/`
- **Foco:** Vagas de tecnologia, engenharia de software, dados, infraestrutura e posições corporativas em empresas russas e multinacionais.
- **Estratégia Técnica:**
  - A API pública `api.hh.ru` passou a exigir autenticação OAuth fechada e bloqueia IPs fora da Rússia (HTTP 403 Forbidden).
  - A skill utiliza requisições web com cabeçalhos de navegador padrão para a rota pública de busca (`https://hh.ru/search/vacancy`) e detalhe de vaga (`https://hh.ru/vacancy/<id>`).
  - O extrator recupera título, empresa, localidade, faixa salarial (em rublos ₽ ou moeda estrangeira), modelo de trabalho (remoto, híbrido, presencial) e descrição.

### 2.2 Habr Career (`habrcareer-search`)
- **Pasta:** `.agents/skills/habrcareer-search/`
- **Foco:** Comunidade técnica especializada (desenvolvedores, DevOps, IA/ML, QA, líderes técnicos).
- **Estratégia Técnica:**
  - Consulta as rotas públicas de vagas (`https://career.habr.ru/vacancies`) com parâmetros de busca (`q`), tipo de vaga e modelo (`remote=1`).
  - Extração de competências técnicas requeridas, senioridade e links de candidatura direta.

---

## 3. Engenharia de Palavras-Chave e Cirílico

### 3.1 Abordagem Híbrida (Inglês vs. Cirílico)
O algoritmo de indexação dos portais russos responde favoravelmente a termos em inglês para a pilha tecnológica, combinados com a profissão em cirílico ou termos internacionais:

| Nomenclatura em Inglês | Título Híbrido Frequente (Cirílico) | Sinônimo Técnico |
| :--- | :--- | :--- |
| `Python Developer` | `Python разработчик` | `Программист Python` |
| `Frontend Engineer` | `Frontend разработчик` | `React / Vue инженер` |
| `Data Scientist` | `Специалист по Data Science` | `Инженер данных` |
| `DevOps Engineer` | `DevOps инженер` | `SRE / Системный инженер` |
| `Machine Learning` | `ML разработчик` | `Инженер машинного обучения` |

### 3.2 Modelos de Trabalho e Níveis de Experiência
- **Remoto:** `Удалённая работа` ou `Удаленка` (`schedule=remote`).
- **Híbrido:** `Гибридный график` (`schedule=hybrid`).
- **Relocation / Visto:** `Релокация` / `Помощь с переездом`.
- **Senioridade:** Стажёр (Junior), Middle, Senior, Lead / Team Lead.

---

## 4. Integração com o Painel e Mapa Mundial

1. **Seletor de Fontes:**
   - Ambas as plataformas estão disponíveis sob o agrupamento **"Global & Internacional"** no menu de fontes do painel:
     - `HeadHunter (Rússia e Eurásia)`
     - `Habr Career (Tech Rússia)`
2. **Resolução Geográfica:**
   - A função `resolveGeo()` no cliente mapeia termos como `Rússia`, `Russia`, `Moscou`, `Moscow`, `São Petersburgo` e `Saint Petersburg` diretamente para o código ISO-2 **`RU`**.
   - As vagas aparecem destacadas no **Mapa Mundial** e na listagem com seus respectivos salários e modelos de trabalho.

---

## 5. Auditoria de Segurança (NVIDIA SkillSpector)

Ambas as skills foram auditadas pelo **SkillSpector**:
- **Score:** `26/100` (Classificação: **MEDIUM / SEGURO**).
- **Zero vulnerabilidades críticas**, sem injeção de prompt e sem dependências ocultas.
