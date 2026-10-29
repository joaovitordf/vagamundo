import { fetchHtml, parseHHSearch, type JobResult } from "../helpers.ts"

export interface SearchOptions {
  query?: string
  remote?: boolean
  jobage?: number
  limit?: number
  format?: string
}

export async function runSearch(opts: SearchOptions): Promise<void> {
  const query = opts.query || "software engineer"
  const params = new URLSearchParams()
  params.set("text", query)
  params.set("items_on_page", String(opts.limit || 25))
  params.set("order_by", "publication_time")

  if (opts.remote) {
    params.set("schedule", "remote")
  }
  if (opts.jobage && opts.jobage > 0) {
    params.set("search_period", String(Math.min(opts.jobage, 30)))
  }

  const url = `https://hh.ru/search/vacancy?${params.toString()}`
  let results: JobResult[] = []

  try {
    const html = await fetchHtml(url)
    results = parseHHSearch(html)
  } catch (err: any) {
    // Retorna lista vazia em caso de falha de conexão graciosa
    results = []
  }

  if (opts.limit && results.length > opts.limit) {
    results = results.slice(0, opts.limit)
  }

  // Contrato do scraper do Job Pindorama espera {"results": [...]}
  console.log(JSON.stringify({ results }, null, 2))
}

