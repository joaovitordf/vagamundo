import type { Flags, JobResult, PortalConfig } from "./types.js"
import {
  cleanHtml,
  decodeHtmlEntities,
  foldAccents,
  inlineText,
  ldLocation,
  readJobPosting,
  tidyPunctuation,
  titleMatches,
} from "./scraper.js"

export * from "./types.js"
export * from "./scraper.js"

export const WORKPLACE_LABELS: Record<string, string> = {
  remote: "Remoto",
  hybrid: "Híbrido",
  "on-site": "Presencial",
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

export function retryAfterMs(header: string | null, now = Date.now()): number | null {
  if (!header) return null
  const value = header.trim()
  if (/^\d+$/.test(value)) return Number(value) * 1000
  const date = Date.parse(value)
  if (Number.isNaN(date)) return null
  return Math.max(date - now, 0)
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

export function contractDate(value: string | null | undefined): string | null {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(String(value ?? "").trim())
  return m ? m[1] : null
}

export function brDate(value: string | null | undefined): string | null {
  const m = /(\d{2})\/(\d{2})\/(\d{4})/.exec(value ?? "")
  return m ? `${m[3]}-${m[2]}-${m[1]}` : null
}

export function relativeDate(text: string | null | undefined, now = new Date()): string | null {
  const t = foldAccents(text ?? "").trim().toLowerCase()
  const shift = (days: number) => new Date(now.getTime() - days * 86_400_000).toISOString().slice(0, 10)
  if (!t) return null
  if (/\b(hoje|today|just now|agora|hora|horas|hour|hours|minuto|minutos|minute|minutes)\b/.test(t)) return shift(0)
  if (/\b(ontem|yesterday)\b/.test(t)) return shift(1)

  // Portuguese: "há N dias", "há N semanas", "há N meses"
  const dPt = /ha\s+(\d+)\s+dias?/.exec(t)
  if (dPt) return shift(Number(dPt[1]))
  const wPt = /ha\s+(\d+)\s+semanas?/.exec(t)
  if (wPt) return shift(Number(wPt[1]) * 7)
  const mPt = /ha\s+(\d+)\s+mes(?:es)?/.exec(t)
  if (mPt) return shift(Number(mPt[1]) * 30)
  if (/ha\s+(?:uma?|1)\s+semana/.test(t)) return shift(7)
  if (/ha\s+(?:um|1)\s+mes/.test(t)) return shift(30)

  // English: "N days ago", "N weeks ago", "N months ago"
  const dEn = /(\d+)\s+days?\s+ago/.exec(t)
  if (dEn) return shift(Number(dEn[1]))
  const wEn = /(\d+)\s+weeks?\s+ago/.exec(t)
  if (wEn) return shift(Number(wEn[1]) * 7)
  const mEn = /(\d+)\s+months?\s+ago/.exec(t)
  if (mEn) return shift(Number(mEn[1]) * 30)
  if (/(?:1|a)\s+week\s+ago/.test(t)) return shift(7)
  if (/(?:1|a)\s+month\s+ago/.test(t)) return shift(30)

  // Standard ISO or BR dates
  const iso = /^(\d{4}-\d{2}-\d{2})/.exec(t)
  if (iso) return iso[1]
  return brDate(t)
}

export function formatSalary(min: number | null | undefined, max: number | null | undefined): string | null {
  const fmt = (n: number) => `R$ ${n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const lo = typeof min === "number" && min > 0 ? min : null
  const hi = typeof max === "number" && max > 0 ? max : null
  if (lo && hi && lo !== hi) return `${fmt(lo)} a ${fmt(hi)}`
  if (lo || hi) return fmt((lo ?? hi) as number)
  return null
}

export function withinJobAge(rows: JobResult[], jobage: number, now = new Date()): JobResult[] {
  if (!(jobage > 0) || jobage >= 9999) return rows
  const cutoff = new Date(now.getTime() - jobage * 86_400_000).toISOString().slice(0, 10)
  return rows.filter((r) => r.date === null || r.date >= cutoff)
}

function cell(text: string | null, width: number): string {
  return (text ?? "—").slice(0, width).padEnd(width)
}

export function renderTable(rows: JobResult[]): string {
  if (rows.length === 0) return "Nenhuma vaga encontrada."
  const idWidth = Math.max(2, ...rows.map((r) => r.id.length))
  const header = [
    cell("ID", idWidth),
    cell("VAGA", 40),
    cell("EMPRESA", 22),
    cell("LOCAL", 24),
    cell("REGIME", 12),
    cell("DATA", 10),
  ].join("  ")
  const body = rows.map((r) =>
    [
      cell(r.id, idWidth),
      cell(r.title, 40),
      cell(r.company, 22),
      cell(r.location, 24),
      cell(r.contract, 12),
      cell(r.date, 10),
    ].join("  "),
  )
  return [header, "-".repeat(header.length), ...body].join("\n")
}

export function renderPlain(rows: JobResult[]): string {
  if (rows.length === 0) return "Nenhuma vaga encontrada."
  return rows
    .map((r) =>
      [
        r.title,
        `  ${r.company ?? "—"} · ${r.location ?? "—"} · ${r.contract ?? "—"} · ${r.date ?? "—"}`,
        r.salary ? `  salário: ${r.salary}` : "",
        r.deadline ? `  inscrições até: ${r.deadline}` : "",
        `  ${r.url ?? "(sem URL)"}`,
      ]
        .filter(Boolean)
        .join("\n"),
    )
    .join("\n\n")
}

export function renderSearch(rows: JobResult[], format: string, page: number, total: number | null): string {
  if (format === "table") return renderTable(rows)
  if (format === "plain") return renderPlain(rows)
  return JSON.stringify({ meta: { count: rows.length, page, total: total ?? rows.length }, results: rows }, null, 2)
}

export function renderDetailPlain(job: JobResult): string {
  const lines: string[] = [job.title, `${job.company ?? "—"} · ${job.location ?? "—"}`]
  const field = (label: string, value: string | null) => {
    if (value) lines.push(`${label}: ${value}`)
  }
  field("Publicada em", job.date)
  field("Inscrições até", job.deadline)
  field("Regime", job.contract)
  field("Modelo de trabalho", job.workplace_type ? (WORKPLACE_LABELS[job.workplace_type] ?? job.workplace_type) : null)
  field("Senioridade", job.seniority)
  field("Salário", job.salary)
  if (job.description) lines.push("", "## Descrição", job.description)
  lines.push("", `URL: ${job.url}`)
  return lines.join("\n")
}

export function parseFlags(argv: string[], alias: Record<string, string>): Flags {
  const flags: Flags = { _: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (!a.startsWith("-")) {
      ;(flags._ as string[]).push(a)
      continue
    }
    const name = a.replace(/^-+/, "")
    const key = alias[name] ?? name
    const next = argv[i + 1]
    let value: string | boolean = true
    if (next !== undefined && !next.startsWith("-")) {
      value = next
      i++
    }
    flags[key] = value
  }
  return flags
}

export function badArg(error: string): number {
  writeError(error, "BAD_ARG")
  return 1
}

export function parseIntFlag(name: string, raw: string | boolean | string[], max?: number): number | null {
  const val = typeof raw === "string" ? Number(raw.trim()) : NaN
  if (!Number.isInteger(val) || val < 1 || (max !== undefined && val > max)) {
    const range = max !== undefined ? `entre 1 e ${max}` : "de pelo menos 1"
    badArg(`--${name} precisa ser um número inteiro ${range}, recebi "${raw}"`)
    return null
  }
  return val
}

export function rejectUnknown(flags: Flags, cmd: string, known: Set<string>): boolean {
  for (const key of Object.keys(flags)) {
    if (key === "_" || known.has(key)) continue
    writeError(
      `opção desconhecida --${key} para '${cmd}': opções nunca são ignoradas em silêncio, porque um filtro descartado muda o resultado; veja --help`,
      "UNKNOWN_FLAG",
    )
    return true
  }
  return false
}

export function rejectEmpty(flags: Flags, names: string[]): boolean {
  for (const name of names) {
    const value = flags[name]
    if (value !== undefined && (typeof value !== "string" || !value.trim())) {
      badArg(`--${name} precisa de um valor`)
      return true
    }
  }
  return false
}

export function createHelpers(config: PortalConfig) {
  const portal = config.portal
  const ua = config.ua
  const timeoutMs = config.timeoutMs ?? 20000
  const retryBudgetMs = config.retryBudgetMs ?? 30000

  async function httpGet(url: string, accept: string): Promise<string | null> {
    const maxRetries = 6
    let delay = 500
    let waited = 0

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      let response: Response
      try {
        response = await fetch(url, {
          headers: { "User-Agent": ua, Accept: accept, "Accept-Language": "pt-BR,pt;q=0.9" },
          redirect: "follow",
          signal: AbortSignal.timeout(timeoutMs),
        })
      } catch (e) {
        throw new Error(`não foi possível acessar ${portal} (${e instanceof Error ? e.message : String(e)})`)
      }

      if (response.status === 429 || response.status >= 500) {
        if (attempt === maxRetries) {
          throw new Error(`${portal} recusou o pedido: ${response.status} ${response.statusText}`)
        }
        const backoff = delay + Math.floor(Math.random() * 500)
        const wait = Math.max(backoff, retryAfterMs(response.headers.get("Retry-After")) ?? 0)
        if (waited + wait > retryBudgetMs) {
          throw new Error(
            `${portal} recusou o pedido: ${response.status} ${response.statusText}; ` +
              `pediu ${Math.ceil(wait / 1000)}s de espera, além do limite de ${retryBudgetMs / 1000}s desta CLI`,
          )
        }
        await sleep(wait)
        waited += wait
        delay = Math.min(delay * 2, 8000)
        continue
      }
      if (response.status === 404) return null
      if (!response.ok) throw new Error(`${portal} recusou o pedido: ${response.status} ${response.statusText}`)
      return await response.text()
    }
    throw new Error(`${portal} recusou o pedido depois de todas as tentativas`)
  }

  return {
    PORTAL: portal,
    UA: ua,
    PORTAL_NAME: portal,
    httpGet,
    writeError,
    retryAfterMs,
    sleep,
    contractDate,
    brDate,
    relativeDate,
    formatSalary,
    withinJobAge,
    renderTable,
    renderPlain,
    renderSearch,
    renderDetailPlain,
    parseFlags,
    badArg,
    parseIntFlag,
    rejectUnknown,
    rejectEmpty,
    WORKPLACE_LABELS,
    cleanHtml,
    decodeHtmlEntities,
    foldAccents,
    inlineText,
    ldLocation,
    readJobPosting,
    tidyPunctuation,
    titleMatches,
  }
}

