#!/usr/bin/env bun
// CLI para buscar vagas 100% remotas globais no RemoteOK (remoteok.com)
// Roda em Bun usando _portal-kit

import {
  PORTAL,
  UA,
  badArg,
  cleanHtml,
  foldAccents,
  httpGet,
  parseFlags,
  parseIntFlag,
  rejectEmpty,
  rejectUnknown,
  renderDetailPlain,
  renderSearch,
  withinJobAge,
  writeError,
  type JobResult,
} from "./helpers.js"

const API_BASE = "https://remoteok.com/api"

const HELP = `remoteok-cli - busca vagas 100% remotas globais no RemoteOK (remoteok.com)

USO
  bun run src/cli.ts search -q "<termo>" [opções] [--format json|table|plain]
  bun run src/cli.ts detail <id|url> [--format json|plain]

BUSCA
  --query, -q <texto>     Palavra-chave, tecnologia ou cargo (ex: python, react, devops)
  --jobage <dias>         Só vagas publicadas nos últimos N dias
  --limit, -n <n>         Quantas vagas exibir (padrão 25)
  --format <fmt>          json (padrão) | table | plain

EXEMPLOS
  bun run src/cli.ts search -q "python" --limit 10 --format table
  bun run src/cli.ts search -q "data engineer" --jobage 14 --format json
  bun run src/cli.ts detail 1137572
`

const KNOWN: Record<string, Set<string>> = {
  search: new Set(["query", "jobage", "limit", "format", "help", "h"]),
  detail: new Set(["format", "help", "h"]),
}

interface RemoteOkItem {
  id?: string | number
  position?: string
  company?: string
  location?: string
  date?: string
  epoch?: number
  url?: string
  apply_url?: string
  salary_min?: number
  salary_max?: number
  tags?: string[]
  description?: string
}

async function fetchRemoteOkFeed(url: string): Promise<RemoteOkItem[]> {
  const res = await fetch(url, {
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      Accept: "application/json",
    },
    signal: AbortSignal.timeout(15000),
  })

  if (!res.ok) {
    throw new Error(`Falha ao acessar RemoteOK: HTTP ${res.status}`)
  }

  const raw = await res.json()
  if (!Array.isArray(raw)) return []
  // Primeiro item do RemoteOK costuma ser aviso legal
  return raw.filter((item): item is RemoteOkItem => Boolean(item && item.id && item.position))
}

async function fetchRemoteOkJobs(query?: string): Promise<RemoteOkItem[]> {
  const clean = (query || "").toLowerCase().trim()
  if (clean && !/\s/.test(clean)) {
    const tagged = await fetchRemoteOkFeed(`${API_BASE}?tag=${encodeURIComponent(clean)}`)
    if (tagged.length > 0) return tagged
  }
  return fetchRemoteOkFeed(API_BASE)
}

function formatSalaryUSD(min?: number, max?: number): string | undefined {
  if (!min && !max) return undefined
  if (min && max) return `USD $${min.toLocaleString()} - $${max.toLocaleString()}/ano`
  if (min) return `A partir de USD $${min.toLocaleString()}/ano`
  return `Até USD $${max!.toLocaleString()}/ano`
}

function itemToJob(item: RemoteOkItem): JobResult {
  const dateStr = item.date
    ? item.date.slice(0, 10)
    : item.epoch
    ? new Date(item.epoch * 1000).toISOString().slice(0, 10)
    : null

  const salaryStr = formatSalaryUSD(item.salary_min, item.salary_max)
  const loc = item.location && item.location.trim() ? item.location.trim() : "Remoto (Global)"

  return {
    id: String(item.id),
    title: item.position || "Sem título",
    company: item.company || "Empresa não informada",
    location: loc,
    date: dateStr,
    deadline: null,
    url: item.url || (item.id ? `https://remoteok.com/remote-jobs/${item.id}` : "https://remoteok.com"),
    apply_url: item.apply_url || item.url,
    workplace_type: "remote",
    salary: salaryStr,
    description: item.description ? cleanHtml(item.description) : undefined,
  }
}

async function main(): Promise<number> {
  const flags = parseFlags(process.argv.slice(2), { q: "query", n: "limit" })
  const cmd = flags._[0]
  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return 0
  }

  const known = KNOWN[cmd]
  if (known && rejectUnknown(flags, cmd, known)) return 1

  if (cmd === "search") {
    if (rejectEmpty(flags, ["query"])) return 1
    const query = typeof flags.query === "string" ? flags.query.trim() : ""
    if (!query) {
      writeError("informe o cargo ou tecnologia com --query/-q", "MISSING_QUERY")
      return 1
    }
    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "table", "plain"].includes(fmt)) {
      return badArg(`--format deve ser json|table|plain, recebi "${fmt}"`)
    }

    let jobage = 9999
    let limit = 25
    if (flags.jobage !== undefined) {
      const v = parseIntFlag("jobage", flags.jobage)
      if (v === null) return 1
      jobage = v
    }
    if (flags.limit !== undefined) {
      const v = parseIntFlag("limit", flags.limit)
      if (v === null) return 1
      limit = v
    }

    try {
      const items = await fetchRemoteOkJobs(query)
      const qNorm = foldAccents(query)
      const terms = qNorm.split(/\s+/).filter(Boolean)

      const filtered = items.filter((item) => {
        const text = foldAccents(
          `${item.position || ""} ${item.company || ""} ${(item.tags || []).join(" ")} ${item.location || ""}`
        )
        if (terms.length > 0 && !terms.every((t) => text.includes(t))) {
          return false
        }
        return true
      })

      let jobs = filtered.map(itemToJob)
      if (jobage < 9999) {
        jobs = withinJobAge(jobs, jobage)
      }

      const results = jobs.slice(0, limit)
      process.stdout.write(renderSearch(results, fmt, 1, jobs.length) + "\n")
      return 0
    } catch (err: any) {
      writeError(`Erro ao buscar no RemoteOK: ${err?.message || err}`, "FETCH_ERROR")
      return 1
    }
  }

  if (cmd === "detail") {
    const target = flags._[1]
    if (!target) {
      writeError("informe o id ou url da vaga", "MISSING_TARGET")
      return 1
    }
    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    try {
      const idMatch = target.match(/(\d+)/)
      const targetId = idMatch ? idMatch[1] : target
      const items = await fetchRemoteOkJobs()
      const found = items.find((i) => String(i.id) === targetId || (i.url && i.url.includes(target)))
      if (!found) {
        writeError(`Vaga ${target} não encontrada no feed recente do RemoteOK`, "NOT_FOUND")
        return 1
      }
      const job = itemToJob(found)
      if (fmt === "json") {
        process.stdout.write(JSON.stringify(job, null, 2) + "\n")
      } else {
        renderDetailPlain(job)
      }
      return 0
    } catch (err: any) {
      writeError(`Erro ao ler vaga no RemoteOK: ${err?.message || err}`, "FETCH_ERROR")
      return 1
    }
  }

  writeError(`comando desconhecido: ${cmd}`, "UNKNOWN_COMMAND")
  return 1
}

main().then((code) => {
  if (code !== 0) process.exit(code)
})
