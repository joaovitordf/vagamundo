# Integração Europeia (EURES) e Google Careers

## 1. Visão Geral

Além do mercado brasileiro e dos 24 portais CLI, o **Vagamundo** monitora oportunidades internacionais e de grandes centros de P&D por meio de coletores Python dedicados em `backend/tools/`:

1. **Rede EURES (European Employment Services):** Portal oficial da Comissão Europeia e Autoridade Europeia do Trabalho (ELA), cobrindo vagas públicas e privadas em países europeus.
2. **Google Careers:** Monitoramento direcionado de engenharia de software, infraestrutura e P&D (incluindo polos do Google no Brasil — Belo Horizonte e São Paulo — além de posições globais).

---

## 2. Coletor EURES (`backend/tools/eures.py`)

### 2.1 Capacidades e Avaliação Dinâmica (Whitelabel)
- Consulta diretamente os índices públicos europeus e normaliza país (`DE`, `NL`, `BE`, `AT`, `FR`, `CH`, `SE`, `ES` etc.), modelo de trabalho, senioridade e requisitos linguísticos.
- **Avaliação orientada ao perfil (`_profile_eures_keywords`):** Em vez de favorecer uma única área fixa, lê dinamicamente `painel_perfil.extract_cv_areas()` para gerar termos de consulta e pontuação (`evaluate_eures_job`, `fetch_eures_for_panel`) aderentes ao currículo configurado da pessoa usuária.
- **Verificação TLS estrita (`_ssl_context`):** Utiliza `ssl.create_default_context()` com validação completa de certificados X.509 habilitada.

### 2.2 Endpoint de Estatísticas Oficiais (`GET /api/eures/stats`)
Disponibiliza ao painel métricas agregadas da base europeia (total de vagas ativas indexadas, recorte em TI, distribuição por país contratante, senioridade e idiomas exigidos).

---

## 3. Coletor Google Careers (`backend/tools/google_careers.py`)

- Implementa coleta estruturada nas listagens públicas do Google Careers com extração de localidade, modalidade (híbrido/presencial/remoto) e requisitos técnicos.
- **Resumos neutros (Whitelabel):** `evaluate_google_job()` avalia afinidade usando termos neutros (`formação na área` e competências técnicas do perfil) sem presumir formação ou endereço específicos no código-fonte.

---

## 4. Integração com a Busca e Filtros

Na arquitetura v2, ambos os coletores integram-se de forma transparente ao `PORTAL_LABELS` (`eures`, `google-careers`) em `frontend/src/app/core/utils/job-filters.util.ts` e aos fluxos do backend (`backend/api/routes/search.py`, `backend/core/scanner.py`), permitindo filtrar resultados europeus (`EU_REMOTE`, códigos ISO-2 no mapa mundial) e oportunidades no Brasil lado a lado.
