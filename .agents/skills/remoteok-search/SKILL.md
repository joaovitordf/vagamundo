---
name: remoteok-search
version: 1.0.0
description: >
  Busca vagas 100% remotas globais no RemoteOK (remoteok.com), agregador internacional de
  tecnologia, desenvolvimento, engenharia e design, com salários em USD e tags de skills.
  Frases de ativação: vagas no RemoteOK, vagas remotas em dólar, vagas internacionais, remoteok.
  English: RemoteOK job search, remote developer jobs, global tech jobs.
context: fork
enabled: true
allowed-tools: Bash(bun run .agents/skills/remoteok-search/cli/src/cli.ts *)
---

# RemoteOK Search

Busca vagas 100% remotas globais na API pública do RemoteOK.

## Uso

```bash
bun run .agents/skills/remoteok-search/cli/src/cli.ts search -q "python" [--limit 25] [--jobage 14] [--format json|table|plain]
bun run .agents/skills/remoteok-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

