# Documentação Técnica — Vagamundo

Este diretório reúne os documentos de arquitetura, guias técnicos e especificações das funcionalidades do **Vagamundo**.

## Índice de Documentos

1. [Arquitetura do Painel Web Local](ARQUITETURA_PAINEL.md)
   - Especificação do frontend Angular 17+ e backend FastAPI.
   - Princípios de segurança, banco SQLite e gateway de IA.

2. [Mapa Mundial e Geolocalização de Oportunidades](MAPA_MUNDIAL_E_GEOLOCALIZACAO.md)
   - Especificação do mapa interativo (Brasil por 27 UFs e Mundo com 172 países).
   - Mecanismo de resolução geográfica e separação de modos de visualização.

3. [Integração Europeia (EURES) e Google Careers](INTEGRACAO_EURES_E_EUROPA.md)
   - Conexão oficial à base da Comissão Europeia / EURES para vagas de tecnologia.
   - Monitoramento das oportunidades de engenharia e IA no Google Careers.

4. [Integração da Rússia e Eurásia (HeadHunter e Habr Career)](INTEGRACAO_RUSSIA_E_EURASIA.md)
   - Integração das plataformas `hh-search` e `habrcareer-search`.
   - Filtros de trabalho remoto internacional e suporte a vistos.

5. [Architecture Decision Records (ADRs)](adr/)
   - [ADR 001: SQLite como Store Primário](adr/001-sqlite-primary-store.md)
   - [ADR 002: FastAPI como Gateway da API Local](adr/002-fastapi-gateway.md)
   - [ADR 003: Dual AI Path](adr/003-dual-ai-path.md)

---
Para orientações de instalação e execução, consulte o [README.md](../README.md) e o [SETUP.md](../SETUP.md).
