# ADR 002: FastAPI como Gateway da API Local

## Contexto
O servidor backend original (`painel.py`) acumulou quase 2.000 linhas de código combinando o servidor HTTP padrão de baixo nível (`http.server.BaseHTTPRequestHandler`), roteamento manual com cadeias de `if/elif`, concorrência com threads cruas, e manipulação de templates. Isso criava um ponto único de falha difícil de testar e manter.

## Decisão
Substituir o manipulador monolítico por uma aplicação moderna em FastAPI com Uvicorn, organizada em módulos coesos (`routes/`, `models.py`, `deps.py`, `security.py`).

## Consequências
- **Positivas:** Roteamento declarativo, validação tipada de dados via Pydantic schemas, suporte nativo a operações assíncronas (`async/await`), documentação OpenAPI automática (`/docs`), e separação limpa de responsabilidades. O servidor HTTP legado (`BaseHTTPRequestHandler`, `SearchJob`, `AgentJob`, `BatchScreeningJob` e `backend/tools/painel/`) foi posteriormente removido por completo de `backend/tools/painel.py`, restando apenas os utilitários puros de persistência JSON/CSV.
- **Atenção:** Requer `fastapi` e `uvicorn` declarados no ambiente Python.

