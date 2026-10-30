#!/usr/bin/env bun
// CLI para buscar vagas remotas no Jobicy (jobicy.com)
// Roda em Bun usando _portal-kit

import {
  PORTAL,
  UA,
  badArg,
  cleanHtml,
  foldAccents,
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

const API_BASE = "https://jobicy.com/api/v2/remote-jobs"

const HELP = `jobicy-cli - busca vagas remotas internacionais no Jobicy (jobicy.com)

USO
  bun run src/cli.ts search -q "<termo>" [opções] [--format json|table|plain]
  bun run src/cli.ts detail <id|url> [--format json|plain]

BUSCA
  --query, -q <texto>     Palavra-chave, tecnologia ou cargo (ex: python, devops, react)
  --geo <região>          Região (ex: latam, usa, europe, uk, canada, apac, any)
  --jobage <dias>         Só vagas publicadas nos últimos N dias
  --limit, -n <n>         Quantas vagas exibir (padrão 25)
  --format <fmt>          json (padrão) | table | plain

EXEMPLOS
  bun run src/cli.ts search -q "fullstack" --limit 10 --format table
  bun run src/cli.ts search -q "python" --geo latam --jobage 14 --format json
  bun run src/cli.ts detail 157922
`

const KNOWN: Record<string, Set<string>> = {
  search: new Set(["query", "geo", "jobage", "limit", "format", "help", "h"]),
  detail: new Set(["format", "help", "h"]),
}

interface JobicyJob {
  id?: number | string
  url?: string
  jobTitle?: string
  companyName?: string
  jobGeo?: string
  jobLevel?: string
  jobType?: string[] | string
  pubDate?: string
  annualSalaryMin?: string | number
  annualSalaryMax?: string | number
  salaryCurrency?: string
  jobDescription?: string
}

async function fetchJobicyJobs(query?: string, geo?: string): Promise<JobicyJob[]> {
  const params = new URLSearchParams()
  params.set("count", "50")
  if (query) params.set("tag", query.toLowerCase().trim())
  if (geo && geo !== "all") params.set("geo", geo.toLowerCase().trim())

  const url = `${API_BASE}?${params.toString()}`
  const res = await fetch(url, {
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      Accept: "application/json",
    },
    signal: AbortSignal.timeout(15000),
  })

  if (!res.ok) {
    throw new Error(`Falha ao acessar Jobicy: HTTP ${res.status}`)
  }

  const raw = await res.json()
  return Array.isArray(raw?.jobs) ? raw.jobs : []
}

function itemToJob(item: JobicyJob): JobResult {
  const dateStr = item.pubDate ? item.pubDate.slice(0, 10) : undefined

  let salaryStr: string | undefined
  if (item.annualSalaryMin || item.annualSalaryMax) {
    const cur = item.salaryCurrency || "USD"
    if (item.annualSalaryMin && item.annualSalaryMax) {
      salaryStr = `${cur} $${Number(item.annualSalaryMin).toLocaleString()} - $${Number(item.annualSalaryMax).toLocaleString()}/ano`
    } else if (item.annualSalaryMin) {
      salaryStr = `A partir de ${cur} $${Number(item.annualSalaryMin).toLocaleString()}/ano`
    } else if (item.annualSalaryMax) {
      salaryStr = `Até ${cur} $${Number(item.annualSalaryMax).toLocaleString()}/ano`
    }
  }

  const loc = item.jobGeo && item.jobGeo.trim() ? item.jobGeo.trim() : "Remoto (Global)"

  return {
    id: String(item.id),
    title: item.jobTitle || "Sem título",
    company: item.companyName || "Empresa não informada",
    location: loc,
    date: dateStr,
    url: item.url || (item.id ? `https://jobicy.com/jobs/${item.id}` : "https://jobicy.com"),
    apply_url: item.url,
    workplace_type: "remote",
    seniority: item.jobLevel || undefined,
    contract: Array.isArray(item.jobType) ? item.jobType.join(", ") : item.jobType || undefined,
    salary: salaryStr,
    description: item.jobDescription ? cleanHtml(item.jobDescription) : undefined,
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

    const geo = typeof flags.geo === "string" ? flags.geo.trim() : undefined
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
      const items = await fetchJobicyJobs(query, geo)
      const qNorm = foldAccents(query)
      const terms = qNorm.split(/\s+/).filter(Boolean)

      const filtered = items.filter((item) => {
        const text = foldAccents(
          `${item.jobTitle || ""} ${item.companyName || ""} ${item.jobGeo || ""} ${item.jobLevel || ""}`
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
      process.stdout.write(renderSearch(results, fmt as "json" | "table" | "plain", 1, jobs.length) + "\n")
      return 0
    } catch (err: any) {
      writeError(`Erro ao buscar no Jobicy: ${err?.message || err}`, "FETCH_ERROR")
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
      const items = await fetchJobicyJobs()
      const found = items.find((i) => String(i.id) === targetId || (i.url && i.url.includes(target)))
      if (!found) {
        writeError(`Vaga ${target} não encontrada no feed recente do Jobicy`, "NOT_FOUND")
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
      writeError(`Erro ao ler vaga no Jobicy: ${err?.message || err}`, "FETCH_ERROR")
      return 1
    }
  }

  writeError(`comando desconhecido: ${cmd}`, "UNKNOWN_COMMAND")
  return 1
}

main().then((code) => {
  if (code !== 0) process.exit(code)
})

