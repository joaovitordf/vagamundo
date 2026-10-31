import { PORTAL, httpGet, renderSearch, withinJobAge, writeError, type JobResult } from "../helpers.js"
import { SEARCH_ACCEPT, parseSearch } from "../parse.js"

export interface SearchOpts {
  url: string // URL de busca já montada por cli.ts (parse.ts sabe o formato do portal)
  fallbackUrl?: string // URL geral caso a tag não exista (404)
  query?: string // termo de busca para filtrar caso use fallbackUrl
  page: number
  limit: number
  jobage: number // 9999 = sem filtro
  format: "json" | "table" | "plain"
  includeDescription: boolean
  keep?: (row: JobResult) => boolean // filtro do lado da CLI, para o que o portal não filtra
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    let body = await httpGet(opts.url, SEARCH_ACCEPT)
    let usingFallback = false
    if (body === null && opts.fallbackUrl) {
      body = await httpGet(opts.fallbackUrl, SEARCH_ACCEPT)
      usingFallback = true
    }
    // Um 404 aqui é a rota que mudou, não "nenhuma vaga": dizer isso como lista
    // vazia esconderia a quebra atrás de um resultado plausível.
    if (body === null) {
      writeError(`a busca de ${PORTAL} não foi encontrada (404): a rota mudou (veja url-reference.md)`, "SEARCH_FAILED")
      return 1
    }
    const parsed = parseSearch(body)
    if (!parsed) {
      writeError(`${PORTAL} devolveu uma resposta num formato inesperado (veja url-reference.md)`, "SEARCH_FAILED")
      return 1
    }
    let rows = withinJobAge(parsed.rows, opts.jobage)
    if (usingFallback && opts.query) {
      const qWords = opts.query.toLowerCase().split(/\s+/).filter(Boolean)
      rows = rows.filter((r) => {
        const titleLower = (r.title ?? "").toLowerCase()
        const tags: string[] = (r as any).tags ?? []
        return qWords.some((w) => titleLower.includes(w) || tags.some((t) => t.toLowerCase().includes(w)))
      })
    }
    if (opts.keep) rows = rows.filter(opts.keep)
    rows = rows.slice(0, opts.limit)
    if (!opts.includeDescription) rows = rows.map((r) => ({ ...r, description: null }))
    process.stdout.write(renderSearch(rows, opts.format, opts.page, parsed.total) + "\n")
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
