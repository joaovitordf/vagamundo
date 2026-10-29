# Documentação do Projeto vagamundo

Este diretório reúne os documentos de arquitetura, guias técnicos e especificações das funcionalidades do `vagamundo`.

## Índice de Documentos

1. [Mapa Mundial e Geolocalização de Oportunidades](MAPA_MUNDIAL_E_GEOLOCALIZACAO.md)
   - Especificação do mapa interativo (Brasil por 27 UFs e Mundo com 172 países).
   - Mecanismo de resolução geográfica e separação de modos de visualização (Volume vs Notas).
   - Otimização de renderização instantânea com `sessionStorage` e deduplicação de requisições.
   - Suporte à localização e baldes internacionais (EUA, Europa, América Latina, Rússia).

2. [Integração Europeia (EURES) e Google Careers](INTEGRACAO_EURES_E_EUROPA.md)
   - Conexão oficial à base da Comissão Europeia / EURES para vagas de tecnologia.
   - Monitoramento das oportunidades de engenharia e IA no Google Careers (BH, SP e Global).
   - Modos de foco de busca (`all`, `google`, `europa`, `cv`).

3. [Integração da Rússia e Eurásia (HeadHunter e Habr Career)](INTEGRACAO_RUSSIA_E_EURASIA.md)
   - Integração das duas maiores plataformas técnicas da Eurásia: `hh-search` e `habrcareer-search`.
   - Estratégias de engenharia de palavras-chave híbridas (Cirílico + Inglês) e sinônimos técnicos.
   - Mecanismos de scraping resilientes e filtros por regime remoto e suporte a visto/relocação.

4. [Arquitetura do Painel Web Local](ARQUITETURA_PAINEL.md)
   - Princípios de segurança: CSP restritivo, anti-CSRF e ausência de injeção insegura (`innerHTML`/`eval`).
   - Estrutura da API REST local (`tools/painel.py`) e componentes do frontend (`tools/painel/index.html`).
   - Randomizador dinâmico de palavras-chave 100% whitelabel baseado no perfil do candidato.
   - Filtro de busca multicamadas em texto completo (título, empresa, descrição, competências e tags).

---
Para orientações de configuração e início rápido, consulte o [COMECE-AQUI.md](../COMECE-AQUI.md) e o [SETUP.md](../SETUP.md).
