---
name: ashby-search
version: 1.0.0
description: >
  Busca vagas nos boards públicos do Ashby (ashbyhq.com), o ATS das maiores startups de tecnologia
  e unicórnios de inteligência artificial (Cursor, Linear, Modal, ElevenLabs, Deepgram, Cognition, Dust, Ramp e Anyscale).
  Frases de ativação: vagas no Ashby, vagas em startups de IA, vagas Cursor, vagas Linear, ashby.
  English: Ashby job board search, AI startups jobs, top tech vacancies.
context: fork
enabled: true
allowed-tools: Bash(bun run .agents/skills/ashby-search/cli/src/cli.ts *)
---

# Ashby Search

Busca vagas nos boards públicos de empresas de ponta que utilizam o ATS Ashby.

## Uso

```bash
bun run .agents/skills/ashby-search/cli/src/cli.ts search -q "engineer" [--boards cursor,linear] [--jobage 14] [--format json|table|plain]
bun run .agents/skills/ashby-search/cli/src/cli.ts detail cursor/<job-id> [--format json|plain]
```

