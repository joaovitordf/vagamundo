import { fetchHtml, parseHabrSearch, type JobResult } from "../helpers.ts"

export interface SearchOptions {
  query?: string
  remote?: boolean
  jobage?: number
  limit?: number
  format?: string
}

export async function runSearch(opts: SearchOptions): Promise<void> {
  const query = opts.query || "developer"
  const params = new URLSearchParams()
  params.set("q", query)
  params.set("type", opts.remote ? "remote" : "all")

  const url = `https://career.habr.ru/vacancies?${params.toString()}`
  let results: JobResult[] = []

  try {
    const html = await fetchHtml(url)
    results = parseHabrSearch(html)
  } catch (err: any) {
    results = []
  }

  if (opts.limit && results.length > opts.limit) {
    results = results.slice(0, opts.limit)
  }

  console.log(JSON.stringify({ results }, null, 2))
}

