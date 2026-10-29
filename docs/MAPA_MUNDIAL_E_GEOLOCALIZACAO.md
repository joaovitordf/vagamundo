# Mapa Mundial Interativo e Geolocalização de Oportunidades

## 1. Visão Geral

O módulo de geolocalização do `vagamundo` integra visualização cartográfica interativa diretamente no painel de oportunidades (`tools/painel.py` e `tools/painel/index.html`), permitindo que a pessoa candidata analise a distribuição geográfica das vagas encontradas tanto no Brasil (dividido por 27 Unidades Federativas) quanto internacionalmente (cobrindo 172 países e pólos de contratação remota).

---

## 2. Componentes e Arquitetura

### 2.1 Dados Cartográficos (`tools/painel/geo_data.json`)
- Contém a definição vetorial compactada (caminhos SVG e centroides) de:
  - **Brasil (27 UFs):** SP, RJ, MG, RS, PR, SC, BA, DF, etc.
  - **Mundo (172 países):** Códigos ISO-2 (BR, US, DE, NL, PT, GB, CA, RU, etc.).
- Não depende de bibliotecas externas pesadas (como Leaflet, Google Maps ou D3), garantindo execução local rápida, offline e com conformidade estrita com a política de Content Security Policy (`CSP`).

### 2.2 Endpoint de Geometria (`GET /api/geo`)
- Implementado no servidor HTTP local (`tools/painel.py`).
- Utiliza **cache em memória (`_GEO_CACHE`)** no backend para evitar leituras repetidas em disco.
- No frontend, utiliza **`sessionStorage`** para cache instantâneo (~1ms) entre recarregamentos e navegação de abas.
- Utiliza padrão de deduplicação via Promise (`geoMapPromise`) para evitar requisições de rede redundantes.

### 2.3 Resolução Geográfica (`resolveGeo(row)`)
A função `resolveGeo` no cliente normaliza a localização informada em cada vaga retornada:
1. **Regime Remoto:** Identifica vagas 100% remotas e as direciona para baldes específicos:
   - `REMOTO_BR`: Remoto Brasil
   - `EU_REMOTE`: Remoto Europa
   - `GLOBAL_REMOTE`: Remoto Internacional / Global
2. **Polos Brasileiros (UFs e Cidades):**
   - Identifica siglas de estado e principais cidades (ex: São Paulo, Campinas, Belo Horizonte, Curitiba, Porto Alegre, Salvador, etc.).
3. **Países Estrangeiros e Eurásia:**
   - Mapeia termos internacionais e países da rede EURES/Américas/Ásia para suas respectivas siglas ISO-2.
   - **Rússia e Eurásia (`RU`):** Mapeamento nativo para vagas vindas do HeadHunter e Habr Career (`Moscou`, `São Petersburgo`, `Novosibirsk`, `Russia`, etc.).

---

## 3. Modos de Visualização e Legendagem

O painel adota uma separação visual limpa entre contagem de vagas e avaliação por IA:

### 3.1 Modo Inicial / Volume de Vagas (Padrão)
- **Quando ativo:** Ao abrir a página e após buscas gerais de vagas, antes de solicitar a triagem por IA.
- **Coloração do Mapa:**
  - `0 vagas`: `#131b2b` (fundo cartográfico neutro)
  - `1 a 4 vagas`: `#0369a1` (azul moderado)
  - `5 a 9 vagas`: `#0284c7` (azul intenso)
  - `10+ vagas`: `#f59e0b` (laranja de alto volume)
- **Rótulos dos Badges:** Apresentam o código do local e a contagem exata (ex.: `BR` / `56 vaga(s)`).

### 3.2 Modo Triagem / Notas de Compatibilidade
- **Quando ativo:** Ao clicar em **"Triar vagas com a IA"** ou ao selecionar filtros de nota (`f-score`).
- **Coloração do Mapa:**
  - `Nota 75+`: `#10b981` (verde esmeralda - forte afinidade)
  - `Nota 60 a 74`: `#0ea5e9` (azul claro - afinidade média)
  - `Nota < 60`: `#64748b` (cinza ardósia - baixa afinidade)
  - `Sem nota calculada`: `#0369a1`
- **Contagem Mantida:** Os números de vagas **permanecem sempre visíveis** no badge (ex.: `56 (85p)` ou `56 vaga(s)`).
- **Controle Manual:** Um botão discreto (`Ver volume de vagas` / `Ver notas da triagem`) permite alternar entre as visões a qualquer momento quando houver vagas triadas.

---

## 4. Otimizações de Desempenho e Segurança

1. **Carregamento Inicial Limpo:**
   - Na abertura da página, o mapa mundial é renderizado imediatamente em estado limpo (vazio), sem pré-carregar vagas de buscas antigas ou disparar pesquisas não solicitadas.
2. **Segurança e CSP:**
   - Todos os elementos SVG e gráficos são criados via `document.createElementNS` e `replaceChildren`.
   - Proibição absoluta de `innerHTML`, `outerHTML` e `eval`, garantindo conformidade com a auditoria de segurança (`tools/security_guards.py`).
