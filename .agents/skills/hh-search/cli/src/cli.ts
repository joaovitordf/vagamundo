#!/usr/bin/env bun
import { runSearch } from "./commands/search.ts"
import { runDetail } from "./commands/detail.ts"

const argv = process.argv.slice(2)
const command = argv[0]

function parseArgs(args: string[]) {
  const flags: Record<string, any> = {}
  for (let i = 0; i < args.length; i++) {
    const a = args[i]
    if (a === "-q" || a === "--query") {
      flags.query = args[++i]
    } else if (a === "--remote") {
      flags.remote = true
    } else if (a === "--jobage") {
      flags.jobage = Number(args[++i])
    } else if (a === "--limit" || a === "-n") {
      flags.limit = Number(args[++i])
    } else if (a === "--format") {
      flags.format = args[++i]
    }
  }
  return flags
}

async function main() {
  if (!command || command === "help" || command === "--help" || command === "-h") {
    console.log(`hh-search — CLI de busca no HeadHunter (hh.ru)

Uso:
  bun run src/cli.ts search [-q <termo>] [--remote] [--jobage <dias>] [--limit <n>] [--format json]
  bun run src/cli.ts detail <url|id>
`)
    process.exit(0)
  }

  if (command === "search") {
    const opts = parseArgs(argv.slice(1))
    await runSearch(opts)
  } else if (command === "detail") {
    const target = argv[1]
    if (!target) {
      console.error("Erro: informe a URL ou ID da vaga para detail")
      process.exit(1)
    }
    await runDetail(target)
  } else {
    // Se o primeiro argumento for direto uma busca ou flags
    const opts = parseArgs(argv)
    await runSearch(opts)
  }
}

main().catch((err) => {
  console.error("Erro:", err.message)
  process.exit(1)
})

