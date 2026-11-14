import { afterEach, describe, expect, test } from "bun:test"
import {
  brDate,
  cleanHtml,
  createHelpers,
  decodeHtmlEntities,
  formatSalary,
  inlineText,
  readJobPosting,
  relativeDate,
  retryAfterMs,
  tidyPunctuation,
  titleMatches,
  withinJobAge,
  type JobResult,
} from "../src/index.js"

const originalFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = originalFetch
})

const row = (date: string | null): JobResult => ({
  id: "1",
  title: "t",
  company: null,
  location: null,
  date,
  url: null,
  deadline: null,
  contract: null,
  workplace_type: null,
  seniority: null,
  salary: null,
  description: null,
})

describe("portal-kit helpers", () => {
  const now = new Date("2026-10-20T12:00:00Z")

  test("relative and absolute dates", () => {
    expect(relativeDate("Hoje", now)).toBe("2026-10-20")
    expect(relativeDate("Ontem", now)).toBe("2026-10-19")
    expect(relativeDate("Há 3 dias", now)).toBe("2026-10-17")
    expect(relativeDate("Há 5 dias", now)).toBe("2026-10-15")
    expect(relativeDate("01/10/2026", now)).toBe("2026-10-01")
    expect(relativeDate("algum dia", now)).toBeNull()
    expect(brDate("25/12/2026")).toBe("2026-12-25")
    expect(brDate("Publicada em 30/09/2026")).toBe("2026-09-30")
  })

  test("withinJobAge keeps recent and dateless rows", () => {
    const rows = [row("2026-10-19"), row("2026-09-01"), row(null)]
    expect(withinJobAge(rows, 14, now).map((r) => r.date)).toEqual(["2026-10-19", null])
    expect(withinJobAge(rows, 9999, now)).toHaveLength(3)
  })

  test("salary formatting", () => {
    expect(formatSalary(5000, 8000)).toContain("5.000,00 a R$ 8.000,00")
    expect(formatSalary(15000, 30000)).toBe("R$ 15.000,00 a R$ 30.000,00")
    expect(formatSalary(12000, 12000)).toBe("R$ 12.000,00")
    expect(formatSalary(0, 0)).toBeNull()
    expect(formatSalary(null, undefined)).toBeNull()
  })

  test("cleanHtml and decodeHtmlEntities", () => {
    expect(cleanHtml("<p>Olá&nbsp;<strong>Mundo</strong></p>")).toBe("Olá Mundo")
    expect(cleanHtml("<p>Olá &amp; bem-vinda</p><ul><li>um</li><li>dois</li></ul>")).toBe(
      "Olá & bem-vinda\n- um\n- dois",
    )
    expect(cleanHtml("")).toBeNull()
    expect(decodeHtmlEntities("Caf&#233; &amp; C&#xF3;digo &quot;ok&quot;")).toBe('Café & Código "ok"')
  })

  test("inline punctuation after tags", () => {
    expect(tidyPunctuation("o backlog , colaborando ( com dados ) .")).toBe(
      "o backlog, colaborando (com dados).",
    )
    expect(tidyPunctuation("- Item\n- Outro")).toBe("- Item\n- Outro")
    expect(tidyPunctuation("Salário: R$ 8.000,00")).toBe("Salário: R$ 8.000,00")
    expect(
      cleanHtml("<p>Gerenciar o <strong>backlog</strong>, com <em>dados</em>.</p><ul><li>Roadmap (<b>Q1</b>)</li></ul>"),
    ).toBe("Gerenciar o backlog, com dados.\n- Roadmap (Q1)")
    expect(inlineText("Atuação <strong>100% remota</strong>.")).toBe("Atuação 100% remota.")
  })

  test("titleMatches", () => {
    expect(titleMatches("Desenvolvedor Angular Pleno", "angular")).toBe(true)
    expect(titleMatches("Desenvolvedor Python", "angular")).toBe(false)
    expect(titleMatches("Senior Product Manager | Pagamentos", "product manager")).toBe(true)
    expect(titleMatches("Analista Contábil Pl", "analista contabil")).toBe(true)
    expect(titleMatches("Gerente de Produtos", "gerente produto")).toBe(true)
    expect(titleMatches("Analista de IA", "ia")).toBe(true)
    expect(titleMatches("IA Generativa", "ia")).toBe(true)
    expect(titleMatches("Atendente Assistência ao Cliente", "ia")).toBe(false)
    expect(titleMatches("Aux. de Operações | Brasília", "ia")).toBe(false)
    expect(titleMatches("Dev C++ / Node.js", "c++ node.js")).toBe(true)
    expect(titleMatches("Qualquer título", "")).toBe(true)
  })

  test("readJobPosting extracts schema.org JobPosting", () => {
    const html = `<script type="application/ld+json">{"@type":"WebSite","name":"x"}</script>
      <script type="application/ld+json">{"@type":"JobPosting","title":"Product Manager","datePosted":"2026-10-16"}</script>`
    expect(readJobPosting(html)?.title).toBe("Product Manager")

    const raw = `<script type="application/ld+json">{"@type":"JobPosting","title":"PM","description":"linha 1\nlinha 2"}</script>`
    expect(readJobPosting(raw)?.description).toBe("linha 1 linha 2")

    const graph = `<script type="application/ld+json">{"@graph":[{"@type":"Organization"},{"@type":"JobPosting","title":"PO"}]}</script>`
    expect(readJobPosting(graph)?.title).toBe("PO")

    expect(readJobPosting(`<script type="application/ld+json">{quebrado</script>`)).toBeNull()
    expect(readJobPosting("<html></html>")).toBeNull()
  })

  test("retryAfterMs parses seconds and HTTP dates", () => {
    expect(retryAfterMs("3")).toBe(3000)
    expect(retryAfterMs(null)).toBeNull()
    expect(retryAfterMs(new Date(Date.now() + 2000).toUTCString())).toBeGreaterThan(0)
  })

  test("createHelpers factory and httpGet behavior", async () => {
    const h = createHelpers({ portal: "Portal Teste", ua: "Mozilla/5.0 (compatible; teste-cli/1.0)" })
    expect(h.PORTAL).toBe("Portal Teste")
    expect(h.UA).toBe("Mozilla/5.0 (compatible; teste-cli/1.0)")
    expect(typeof h.httpGet).toBe("function")

    globalThis.fetch = (async () => new Response("nada", { status: 404 })) as unknown as typeof fetch
    expect(await h.httpGet("https://exemplo.invalid/x", "text/html")).toBeNull()

    let ua = ""
    globalThis.fetch = (async (_: unknown, init?: RequestInit) => {
      ua = new Headers(init?.headers).get("User-Agent") ?? ""
      return new Response("ok")
    }) as unknown as typeof fetch
    await h.httpGet("https://exemplo.invalid/x", "text/html")
    expect(ua).toMatch(/^Mozilla\/5\.0 \(compatible; [a-z]+-cli\/1\.0\)$/)
  })
})

