#!/usr/bin/env bun
// CLI para buscar vagas nos boards públicos do Ashby (ashbyhq.com).
// Roda em Bun ou Node.js usando _portal-kit

import process from "process"
import { resolve, dirname } from "path"
import { fileURLToPath } from "url"
import { readFileSync, existsSync } from "fs"

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

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const API_BASE = "https://api.ashbyhq.com/posting-api/job-board"
const BOARDS_FILE = resolve(__dirname, "../../boards.txt")

const HELP = `ashby-cli - busca vagas em empresas nos boards públicos do Ashby (ashbyhq.com)

USO
  bun run src/cli.ts search -q "<termo>" [opções] [--format json|table|plain]
  bun run src/cli.ts detail <board/id|url> [--format json|plain]

BUSCA
  --query, -q <texto>     Cargo ou termo no título (ex: engineer, product, designer)
  --boards <lista>        Slugs das empresas separados por vírgula (padrão: boards.txt)
  --jobage <dias>         Só vagas publicadas nos últimos N dias
  --limit, -n <n>         Quantas vagas exibir (padrão 25)
  --format <fmt>          json (padrão) | table | plain

EXEMPLOS
  bun run src/cli.ts search -q "engineer" --format table
  bun run src/cli.ts search -q "frontend" --boards cursor,linear --format json
  bun run src/cli.ts detail cursor/b66e3ef5-75ea-4dc3-8b77-cfbbf31fa923
`

const KNOWN: Record<string, Set<string>> = {
  search: new Set(["query", "boards", "jobage", "limit", "format", "help", "h"]),
  detail: new Set(["format", "help", "h"]),
}

interface AshbyJob {
  id: string
  title: string
  location?: string
  department?: string
  team?: string
  isRemote?: boolean
  publishedAt?: string
  jobUrl?: string
  applyUrl?: string
  descriptionHtml?: string
}

function loadDefaultBoards(): string[] {
  if (!existsSync(BOARDS_FILE)) return ["cursor", "linear", "elevenlabs", "ramp"]
  return readFileSync(BOARDS_FILE, "utf-8")
    .split("\n")
    .map((s: string) => s.trim().toLowerCase())
    .filter((s: string) => Boolean(s) && !s.startsWith("#"))
}

function formatCompanyName(slug: string): string {
  const special: Record<string, string> = {
    elevenlabs: "ElevenLabs",
    deepgram: "Deepgram",
    togetherai: "Together AI",
    anyscale: "Anyscale",
  }
  if (special[slug]) return special[slug]
  return slug.charAt(0).toUpperCase() + slug.slice(1)
}

async function fetchBoardJobs(board: string): Promise<AshbyJob[]> {
  const url = `${API_BASE}/${encodeURIComponent(board)}`
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0" },
      signal: AbortSignal.timeout(10000),
    })
    if (!res.ok) return []
    const data = (await res.json()) as any
    return Array.isArray(data?.jobs) ? data.jobs : []
  } catch {
    return []
  }
}

function itemToJob(board: string, item: AshbyJob): JobResult {
  const dateStr = item.publishedAt ? item.publishedAt.slice(0, 10) : null
  const company = formatCompanyName(board)
  const loc = item.location && item.location.trim() ? item.location.trim() : item.isRemote ? "Remoto" : "Não informado"

  return {
    id: `${board}/${item.id}`,
    title: item.title || "Sem título",
    company,
    location: loc,
    date: dateStr,
    url: item.jobUrl || `https://jobs.ashbyhq.com/${board}/${item.id}`,
    deadline: null,
    apply_url: item.applyUrl || item.jobUrl || null,
    workplace_type: item.isRemote ? "remote" : "on-site",
    description: item.descriptionHtml ? cleanHtml(item.descriptionHtml) : null,
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
      writeError("informe o termo ou cargo com --query/-q", "MISSING_QUERY")
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

    const boards: string[] =
      typeof flags.boards === "string"
        ? flags.boards.split(",").map((s: string) => s.trim().toLowerCase()).filter(Boolean)
        : loadDefaultBoards()

    try {
      const allJobs: JobResult[] = []
      const qNorm = foldAccents(query)
      const terms = qNorm.split(/\s+/).filter(Boolean)

      // Executa buscas nos boards em paralelo
      await Promise.all(
        boards.map(async (b: string) => {
          const raw = await fetchBoardJobs(b)
          for (const item of raw) {
            const text = foldAccents(`${item.title || ""} ${item.department || ""} ${item.team || ""} ${item.location || ""}`)
            if (terms.length > 0 && !terms.every((t: string) => text.includes(t))) {
              continue
            }
            const job = itemToJob(b, item)
            allJobs.push(job)
          }
        })
      )

      let results = allJobs
      if (jobage < 9999) {
        results = withinJobAge(results, jobage)
      }

      const paginated = results.slice(0, limit)
      process.stdout.write(renderSearch(paginated, fmt as "json" | "table" | "plain", 1, results.length) + "\n")
      return 0
    } catch (err: any) {
      writeError(`Erro ao buscar no Ashby: ${err?.message || err}`, "FETCH_ERROR")
      return 1
    }
  }

  if (cmd === "detail") {
    const target = flags._[1]
    if (!target) {
      writeError("informe o id da vaga (formato: empresa/id ou url)", "MISSING_TARGET")
      return 1
    }
    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    try {
      let board = ""
      let id = ""
      const urlMatch = target.match(/ashbyhq\.com\/([^/]+)\/([^/?#]+)/)
      if (urlMatch) {
        board = urlMatch[1]
        id = urlMatch[2]
      } else if (target.includes("/")) {
        const parts = target.split("/")
        board = parts[0]
        id = parts[1]
      } else {
        board = "cursor"
        id = target
      }

      const jobs = await fetchBoardJobs(board)
      const found = jobs.find((j: AshbyJob) => j.id === id)
      if (!found) {
        writeError(`Vaga ${target} não encontrada no board ${board}`, "NOT_FOUND")
        return 1
      }
      const job = itemToJob(board, found)
      if (fmt === "json") {
        process.stdout.write(JSON.stringify(job, null, 2) + "\n")
      } else {
        renderDetailPlain(job)
      }
      return 0
    } catch (err: any) {
      writeError(`Erro ao ler vaga no Ashby: ${err?.message || err}`, "FETCH_ERROR")
      return 1
    }
  }

  writeError(`comando desconhecido: ${cmd}`, "UNKNOWN_COMMAND")
  return 1
}

main().then((code: number) => {
  if (code !== 0) process.exit(code)
})
