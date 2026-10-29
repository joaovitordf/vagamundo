# Integração Europeia (EURES) e Google Careers

## 1. Visão Geral

Para além do mercado nacional brasileiro, o `vagamundo` monitora oportunidades internacionais em tecnologia com foco em:
1. **Rede EURES (European Employment Services):** Portal oficial da Comissão Europeia e Autoridade Europeia do Trabalho (ELA), cobrindo vagas públicas e privadas em 31 países europeus.
2. **Google Careers:** Monitoramento focado em centros de desenvolvimento e engenharia de software (com destaque para os pólos de Belo Horizonte e São Paulo, além de posições globais).

---

## 2. Coletor EURES (`tools/eures.py`)

### 2.1 Capacidades
- Realiza consultas diretamente aos índices públicos da União Europeia.
- Filtra por ocupações do grupo ISCO (Engenharia de Software, Ciência de Dados, Visão Computacional, Inteligência Artificial).
- Mapeia países como Alemanha (DE), Holanda (NL), Bélgica (BE), Áustria (AT), França (FR), Suíça (CH), Suécia (SE), Espanha (ES), entre outros.
- Obtém metadados de elegibilidade internacional, requisitos linguísticos (inglês, alemão, francês, holandês) e faixas de senioridade.

### 2.2 Endpoint de Estatísticas Oficiais (`GET /api/eures/stats`)
- Fornece ao painel métricas agregadas da base europeia:
  - Total geral de vagas ativas na Europa (~1,9 milhão).
  - Vagas do setor de Tecnologia da Informação (~66 mil).
  - Distribuição dos principais países contratantes em TI.
  - Índices de senioridade e requisitos linguísticos demandados.

---

## 3. Coletor Google Careers (`tools/google_careers.py`)

- Implementa busca direcionada nas listagens públicas do Google Careers.
- Foco em vagas para graduação em Ciência da Computação / Engenharia de Software.
- Segmentação prioritária nos escritórios do Google Brasil (Belo Horizonte - Centro de P&D em IA, e São Paulo), com identificação de modelos híbridos e remotos.

---

## 4. Modos de Foco de Busca

O console de busca do painel permite selecionar o escopo desejado através do parâmetro `focus`:
- `all`: Busca em todas as fontes (portais brasileiros, internacionais e Europa EURES).
- `google`: Busca prioritária no Google Careers (BH, SP e Global).
- `europa`: Busca direcionada na rede EURES (Engenharia de Software, Visão Computacional e IA na Europa).
- `cv`: Busca orientada a Visão Computacional e Machine Learning nos portais suportados.
