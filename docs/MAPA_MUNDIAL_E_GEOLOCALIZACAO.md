# Mapa Mundial Interativo e Geolocalização de Oportunidades

## 1. Visão Geral

O módulo de geolocalização do **Vagamundo** oferece visualização cartográfica interativa diretamente na tela **Buscar e Vagas** (`/buscar-vagas`), permitindo analisar a distribuição geográfica das oportunidades no **Brasil (27 Unidades Federativas)** e no **Mundo (172 países)** além dos fluxos remotos.

---

## 2. Componentes e Arquitetura

### 2.1 Dados Cartográficos (`geo_data.json`)
- O arquivo vetorial compactado (caminhos SVG e centroides de 27 UFs BR e 172 códigos ISO-2 globais) reside em `frontend/src/assets/geo_data.json` (servido pelo backend via `GET /api/geo` e como fallback local no Angular).
- Não depende de bibliotecas externas (como Leaflet, Google Maps ou D3), garantindo carregamento offline imediato, zero vazamento de telemetria a terceiros e conformidade total com CSP.

### 2.2 Endpoint e Cache (`GET /api/geo`)
- Servido pelo backend FastAPI (`backend/api/routes/search.py`), utilizando `ApiService.getGeo()` no Angular.
- No frontend, o estado cartográfico e os filtros ativos são gerenciados de forma reativa por `SearchStateService` (persistido em `localStorage` sob `vagamundo.searchState.v1`) e cache de geometria em `sessionStorage`.

### 2.3 Resolução Geográfica (`resolveGeo` em `frontend/src/app/core/utils/job-filters.util.ts`)
A função pura `resolveGeo` normaliza a localidade e o portal de cada vaga em uma estrutura `GeoResolution`:
1. **Regime Remoto:** Separa oportunidades 100% remotas em baldes dedicados (`REMOTO_BR`, `EU_REMOTE`, `GLOBAL_REMOTE`) considerando `BR_PORTALS` e termos do anúncio.
2. **Polos Brasileiros (UFs e Cidades):** Reconhece siglas estaduais e centenas de nomes de municípios (`BR_UF_WORDS`) para atribuir a respectiva UF (`SP`, `MG`, `RJ`, `PR`, `SC`, `RS`, etc.).
3. **Países Estrangeiros e Eurásia:** Mapeia países da Europa/EURES, Américas, Ásia e Eurásia para seus códigos ISO-2 (incluindo mapeamento nativo `RU` para `Moscou`, `São Petersburgo`, `HeadHunter`, `Habr Career` etc.).

Clicar em um estado, país ou badge remoto aplica `ActiveGeoFilter` imediatamente sobre a lista de vagas exibida.

---

## 3. Modos de Visualização e Legendagem

Em `BuscarVagasComponent` (`frontend/src/app/features/buscar-vagas/buscar-vagas.component.ts`), a visualização alterna entre **Volume de Vagas** e **Notas da Triagem IA**:

- **Modo Volume (Padrão):** Destaca densidade de oportunidades por localidade (0 vagas em neutro, faixas crescentes de azul até alto volume em âmbar) com badges exibindo o código e a contagem exata.
- **Modo Triagem IA:** Quando há vagas avaliadas, permite colorir pelas faixas de nota (`75+` verde, `60–74` azul claro, `< 60` ardósia) mantendo sempre a contagem visível no badge, com alternância manual a qualquer momento.

---

## 4. Segurança (DOM SVG Puro, Zero `innerHTML`)

Para eliminar qualquer superfície de XSS armazenado caso um título, cidade ou nome de país venha malformado de um portal externo:
- As funções `renderWorldMapSvg`, `renderBrasilMapSvg`, `createSvgEl`, `appendOceanGradient` e `createMapBadge` em `BuscarVagasComponent` constroem toda a árvore SVG usando exclusivamente `document.createElementNS('http://www.w3.org/2000/svg', ...)`, `.replaceChildren()` e `.textContent`.
- O uso de `innerHTML`, `outerHTML`, `eval` ou inserções de HTML bruto no painel é bloqueado automaticamente por `backend/tools/security_guards.py` (verificação executada em testes e CI).
