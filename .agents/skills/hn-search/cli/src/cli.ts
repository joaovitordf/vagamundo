#!/usr/bin/env bun
// CLI para buscar vagas na thread "Who is hiring?" do Hacker News via API Algolia.
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

const ALGOLIA_SEARCH_DATE = "https://hn.algolia.com/api/v1/search_by_date"
const ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"

const HELP = `hn-cli - busca vagas na thread "Who is hiring?" do Hacker News (news.ycombinator.com)

USO
  bun run src/cli.ts search -q "<termo>" [opções] [--format json|table|plain]
  bun run src/cli.ts detail <id|url> [--format json|plain]

BUSCA
  --query, -q <texto>     Palavra-chave, tecnologia ou cargo (ex: python, rust, remote)
  --jobage <dias>         Só vagas publicadas nos últimos N dias
  --limit, -n <n>         Quantas vagas exibir (padrão 25)
  --format <fmt>          json (padrão) | table | plain

EXEMPLOS
  bun run src/cli.ts search -q "python" --limit 10 --format table
  bun run src/cli.ts search -q "staff engineer" --format json
  bun run src/cli.ts detail 50095921
`

const KNOWN: Record<string, Set<string>> = {
  search: new Set(["query", "jobage", "limit", "format", "help", "h"]),
  detail: new Set(["format", "help", "h"]),
}

interface HnComment {
  objectID: string
  created_at: string
  author: string
  comment_text?: string
  story_id?: number
}

async function getLatestWhoIsHiringStoryId(): Promise<string> {
  const url = `${ALGOLIA_SEARCH_DATE}?tags=story,author_whoishiring&query=%22Who+is+hiring%22&hitsPerPage=1`
  const res = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0" },
    signal: AbortSignal.timeout(10000),
  })
  if (!res.ok) throw new Error(`Falha ao buscar thread Who is hiring: HTTP ${res.status}`)
  const data = await res.json()
  const hit = data?.hits?.[0]
  if (!hit?.objectID) throw new Error("Nenhuma thread Who is hiring encontrada")
  return hit.objectID
}

async function searchHnJobs(query: string, storyId: string): Promise<HnComment[]> {
  const url = `${ALGOLIA_SEARCH}?tags=comment,story_${storyId}&query=${encodeURIComponent(query)}&hitsPerPage=60`
  const res = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0" },
    signal: AbortSignal.timeout(15000),
  })
  if (!res.ok) throw new Error(`Falha ao buscar comentários no HN: HTTP ${res.status}`)
  const data = await res.json()
  return Array.isArray(data?.hits) ? data.hits : []
}

function parseCommentToJob(c: HnComment): JobResult {
  const rawHtml = c.comment_text || ""
  const clean = cleanHtml(rawHtml) || ""
  const firstLine = clean.split("\n")[0] || ""
  const parts = firstLine.split(/\s*\|\s*/).map((p) => p.trim())

  let company = "Startup / Empresa"
  let title = "Oportunidade Tech"
  let location = "Remoto / Global"

  if (parts.length >= 3) {
    company = parts[0] || company
    title = parts[1] || title
    location = parts[2] || location
  } else if (parts.length === 2) {
    company = parts[0] || company
    title = parts[1] || title
  } else if (parts.length === 1 && parts[0]) {
    title = parts[0]
  }

  const locFold = foldAccents(location + " " + clean)
  let workplaceType: "remote" | "hybrid" | "on_site" = "on_site"
  if (locFold.includes("remote") || locFold.includes("anywhere") || locFold.includes("worldwide")) {
    workplaceType = "remote"
  } else if (locFold.includes("hybrid") || locFold.includes("hibrido")) {
    workplaceType = "hybrid"
  }

  const dateStr = c.created_at ? c.created_at.slice(0, 10) : null

  return {
    id: c.objectID,
    title,
    company,
    location,
    date: dateStr,
    deadline: null,
    url: `https://news.ycombinator.com/item?id=${c.objectID}`,
    apply_url: `https://news.ycombinator.com/item?id=${c.objectID}`,
    workplace_type: workplaceType,
    description: clean,
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
      writeError("informe o termo ou tecnologia com --query/-q", "MISSING_QUERY")
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
      const storyId = await getLatestWhoIsHiringStoryId()
      const comments = await searchHnJobs(query, storyId)

      let jobs = comments.map(parseCommentToJob)
      if (jobage < 9999) {
        jobs = withinJobAge(jobs, jobage)
      }

      const results = jobs.slice(0, limit)
      process.stdout.write(renderSearch(results, fmt as "json" | "table" | "plain", 1, jobs.length) + "\n")
      return 0
    } catch (err: any) {
      writeError(`Erro ao buscar no Hacker News: ${err?.message || err}`, "FETCH_ERROR")
      return 1
    }
  }

  if (cmd === "detail") {
    const target = flags._[1]
    if (!target) {
      writeError("informe o id do comentário ou url", "MISSING_TARGET")
      return 1
    }
    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    try {
      const idMatch = target.match(/(\d+)/)
      const targetId = idMatch ? idMatch[1] : target
      const res = await fetch(`https://hn.algolia.com/api/v1/items/${targetId}`, {
        headers: { "User-Agent": "Mozilla/5.0" },
        signal: AbortSignal.timeout(10000),
      })
      if (!res.ok) {
        writeError(`Vaga ${target} não encontrada no Hacker News`, "NOT_FOUND")
        return 1
      }
      const raw = await res.json()
      const job = parseCommentToJob({
        objectID: String(raw.id),
        created_at: raw.created_at,
        author: raw.author,
        comment_text: raw.text,
      })
      if (fmt === "json") {
        process.stdout.write(JSON.stringify(job, null, 2) + "\n")
      } else {
        renderDetailPlain(job)
      }
      return 0
    } catch (err: any) {
      writeError(`Erro ao ler vaga no Hacker News: ${err?.message || err}`, "FETCH_ERROR")
      return 1
    }
  }

  writeError(`comando desconhecido: ${cmd}`, "UNKNOWN_COMMAND")
  return 1
}

main().then((code) => {
  if (code !== 0) process.exit(code)
})

