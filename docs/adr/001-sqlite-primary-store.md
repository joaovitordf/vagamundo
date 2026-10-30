# ADR 001: SQLite como Store Primário de Persistência

## Contexto
Anteriormente, o Vagamundo utilizava arquivos planos de texto (`seen_jobs.json` e `job_search_tracker.csv`) como armazenamento primário. Essa abordagem gerava problemas críticos:
1. Ausência de atomicidade nas gravações (`write_text` direto sobrescrevendo arquivos inteiros).
2. Risco de corrupção ou *race conditions* quando buscas concorrentes ou requisições do painel ocorriam simultaneamente.
3. Consultas lentas para filtragem por status, pontuação ou termos de busca em grandes volumes de vagas.

## Decisão
Adotamos o SQLite local (`data/vagamundo.db`) com modo WAL (`Write-Ahead Logging`) e chave estrangeira ativa como o banco de dados primário do Vagamundo v2. Arquivos JSON e CSV continuam sendo suportados como formatos de exportação e compatibilidade retroativa.

## Consequências
- **Positivas:** Transações ACID completas, integridade referencial com `ON DELETE CASCADE`, consultas indexadas de alta velocidade, e proteção total contra perda de histórico em quedas abruptas.
- **Atenção:** Os agentes interativos de terminal continuam utilizando ferramentas CLI que interagem de forma transparente com o banco de dados.

