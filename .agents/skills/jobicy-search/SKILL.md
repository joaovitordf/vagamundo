---
name: jobicy-search
version: 1.0.0
description: >
  Busca vagas 100% remotas internacionais no Jobicy (jobicy.com), com foco em tecnologia,
  desenvolvimento, dados, produto e engenharia, com filtros regionais (EUA, Europa, LATAM, Global).
  Frases de ativação: vagas no Jobicy, vagas remotas internacionais, jobicy, vagas tech globais.
  English: Jobicy job search, remote jobs worldwide, international developer jobs.
context: fork
enabled: true
allowed-tools: Bash(bun run .agents/skills/jobicy-search/cli/src/cli.ts *)
---

# Jobicy Search

Busca vagas 100% remotas globais na API pública v2 do Jobicy.

## Uso

```bash
bun run .agents/skills/jobicy-search/cli/src/cli.ts search -q "python" [--geo latam|usa|europe|all] [--limit 25] [--jobage 14] [--format json|table|plain]
bun run .agents/skills/jobicy-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

