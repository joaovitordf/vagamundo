---
name: habrcareer-search
version: 1.0.0
description: >
  Busca vagas de tecnologia no Habr Career (career.habr.ru), a plataforma de
  recrutamento especializada da maior comunidade técnica da Rússia (Habr).
  Focada em desenvolvedores de software, engenharia de dados, inteligência artificial,
  arquitetura e DevOps, com suporte a filtros de trabalho remoto e contratação internacional.
  Frases de ativação: vagas no Habr Career, vagas de tecnologia Rússia, Habr vagas,
  "tem vaga no Habr Career?", ler esta vaga do Habr.
  English: Habr Career jobs, Russian tech jobs, developer jobs in Russia, Habr vacancies.
context: fork
enabled: true
allowed-tools: Bash(bun run .agents/skills/habrcareer-search/cli/src/cli.ts *)
---

# Busca no Habr Career (career.habr.ru)

Busca vagas de tecnologia no **[Habr Career](https://career.habr.ru)**.

## Como usar
```bash
bun run .agents/skills/habrcareer-search/cli/src/cli.ts search -q "Python" --remote
bun run .agents/skills/habrcareer-search/cli/src/cli.ts detail "https://career.habr.ru/vacancies/1000168375"
```

