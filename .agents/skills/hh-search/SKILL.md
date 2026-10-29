---
name: hh-search
version: 1.0.0
description: >
  Busca vagas de emprego e tecnologia no HeadHunter (hh.ru), a maior plataforma de
  recrutamento da Rússia e do Leste Europeu. Suporta filtros por modelo de trabalho
  (remoto internacional, híbrido, presencial e com pacote de realocação/visto),
  com consultas otimizadas em inglês para atração de empresas multiculturais.
  Frases de ativação: vagas na Rússia, vagas no hh.ru, vagas remotas Rússia,
  buscar no HeadHunter, "tem vaga de X na Rússia?", ler esta vaga do hh.ru.
  English: Russian job search, HeadHunter Russia jobs, hh.ru jobs, remote jobs in Russia.
context: fork
enabled: true
allowed-tools: Bash(bun run .agents/skills/hh-search/cli/src/cli.ts *)
---

# Busca no HeadHunter (hh.ru)

Busca vagas abertas no **[HeadHunter (hh.ru)](https://hh.ru)** — o principal ecossistema de contratação da Rússia.

## ⚠️ Estratégia de Palavras-Chave para Estrangeiros
Recomenda-se buscar com **termos em inglês** (ex.: `Python developer`, `Frontend`, `Computer Vision`, `Angular`).
Empresas na Rússia que publicam títulos e requisitos em inglês são as preparadas para contratação remota internacional e/ou realocação com suporte a visto.

## Como usar
```bash
bun run .agents/skills/hh-search/cli/src/cli.ts search -q "Python developer" --remote
bun run .agents/skills/hh-search/cli/src/cli.ts detail "https://hh.ru/vacancy/11482019"
```

