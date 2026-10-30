# ADR 003: Coexistência de Dois Caminhos de IA (Dual-Path)

## Contexto
O ecossistema do Vagamundo é utilizado tanto por desenvolvedores operando ferramentas de IA no terminal (como Google Antigravity, Codex CLI e Claude Code através dos seus planos de assinatura) quanto por meio da interface gráfica web para triagens rápidas em lote.

## Decisão
Validar e formalizar a coexistência de dois caminhos de IA:
1. **Caminho 1 — Agent CLI:** O assistente de IA lê as especificações canônicas em `.claude/skills/` e `.claude/commands/`, executando comandos interativos (`/scrape`, `/rank`, `/apply`, `/upskill`, `/interview`). Consome o plano do usuário no CLI do agente.
2. **Caminho 2 — Direct API (Headless):** O gateway FastAPI utiliza `core/ai_mux.py` para operações disparadas diretamente por cliques de botões na interface web (avaliação rápida, triagem em lote), utilizando as chaves de API configuradas no `.env`.

## Consequências
- Os arquivos em `.claude/` e os `SKILL.md` de portal permanecem intocados e protegidos como fonte canônica da verdade.
- Ambos os caminhos compartilham a mesma base de dados SQLite (`data/vagamundo.db`) e o mesmo sistema de arquivos.

