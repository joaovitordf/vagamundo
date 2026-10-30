---
name: hn-search
version: 1.0.0
description: >
  Busca vagas nas threads mensais "Ask HN: Who is hiring?" do Hacker News via API Algolia,
  com posts diretos de fundadores e líderes técnicos de startups e empresas globais de ponta.
  Frases de ativação: vagas no Hacker News, vagas do HN, who is hiring, vagas startups globais.
  English: Hacker News who is hiring job search, HN tech jobs, startup jobs.
context: fork
enabled: true
allowed-tools: Bash(bun run .agents/skills/hn-search/cli/src/cli.ts *)
---

# Hacker News ("Who is Hiring?") Search

Busca vagas diretamente nos comentários da thread mensal "Who is hiring?" do Hacker News.

## Uso

```bash
bun run .agents/skills/hn-search/cli/src/cli.ts search -q "python" [--limit 25] [--format json|table|plain]
bun run .agents/skills/hn-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

