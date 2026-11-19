export interface JobResult {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string | null
  deadline: string | null
  contract: string | null
  workplace_type: "remote" | "hybrid" | "on-site" | null
  seniority: string | null
  salary: string | null
  description: string | null
  country_code: string | null
  signals: string[]
}

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

export async function fetchHtml(url: string): Promise<string> {
  const maxRetries = 3
  let delay = 1000
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(url, {
        headers: {
          "User-Agent": UA,
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "Accept-Language": "en-US,en;q=0.9,ru;q=0.8"
        },
        signal: AbortSignal.timeout(20000)
      })
      if (res.status === 429 || res.status >= 500) {
        if (attempt === maxRetries) throw new Error(`hh.ru retornou status ${res.status}`)
        await new Promise((r) => setTimeout(r, delay))
        delay *= 2
        continue
      }
      if (!res.ok) throw new Error(`hh.ru retornou status ${res.status}: ${res.statusText}`)
      return await res.text()
    } catch (err: any) {
      if (attempt === maxRetries) throw err
      await new Promise((r) => setTimeout(r, delay))
      delay *= 2
    }
  }
  throw new Error("Falha ao conectar com hh.ru após múltiplas tentativas")
}

export function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
}

export function cleanHtml(html: string | null | undefined): string | null {
  if (!html) return null
  const withBreaks = html
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/(p|li|ul|ol|div|h\d)>/gi, "\n")
  const text = decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, " "))
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
  return text || null
}

export function detectWorkplace(title: string, location: string, desc: string): "remote" | "hybrid" | "on-site" {
  const combined = `${title} ${location} ${desc}`.toLowerCase()
  if (combined.includes("remote") || combined.includes("удален") || combined.includes("дистанцион")) {
    return "remote"
  }
  if (combined.includes("hybrid") || combined.includes("гибрид")) {
    return "hybrid"
  }
  return "on-site"
}

export function parseHHSearch(html: string): JobResult[] {
  const results: JobResult[] = []
  const seenUrls = new Set<string>()

  const titleRegex = /<a[^>]*data-qa="serp-item__title"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi
  const matches: Array<{ index: number; href: string; rawTitle: string }> = []
  let m: RegExpExecArray | null

  while ((m = titleRegex.exec(html)) !== null) {
    matches.push({ index: m.index, href: m[1], rawTitle: m[2] })
  }

  for (let i = 0; i < matches.length; i++) {
    const entry = matches[i]
    let rawUrl = entry.href
    if (rawUrl.startsWith("/")) rawUrl = `https://hh.ru${rawUrl}`
    const cleanUrl = rawUrl.split("?")[0]
    if (!cleanUrl.includes("/vacancy/")) continue
    if (seenUrls.has(cleanUrl)) continue
    seenUrls.add(cleanUrl)

    const idMatch = cleanUrl.match(/\/vacancy\/(\d+)/)
    const id = idMatch ? `hh-${idMatch[1]}` : `hh-${Date.now()}-${results.length}`
    const title = decodeHtmlEntities(entry.rawTitle.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim())

    const startIdx = Math.max(0, entry.index - 200)
    const nextIdx = i + 1 < matches.length ? matches[i + 1].index : Math.min(html.length, entry.index + 14000)
    const endIdx = Math.min(html.length, nextIdx, entry.index + 14000)
    const block = html.slice(startIdx, endIdx)

    // Empresa (tenta wrapper dedicado de texto ou link completo removendo tags internas)
    const empMatch =
      block.match(/data-qa="vacancy-serp__vacancy-employer-text"[^>]*>([\s\S]*?)<\/span>/i) ||
      block.match(/data-qa="vacancy-serp__vacancy-employer"[^>]*>([\s\S]*?)<\/a>/i)
    const company = empMatch
      ? decodeHtmlEntities(empMatch[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()) || null
      : null

    // Salário
    const salMatch = block.match(/data-qa="vacancy-serp__vacancy-compensation"[^>]*>([\s\S]*?)<\/span>/i)
    const salary = salMatch
      ? decodeHtmlEntities(salMatch[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()) || null
      : null

    // Endereço / Local
    const addrMatch = block.match(/data-qa="vacancy-serp__vacancy-address"[^>]*>([\s\S]*?)<\/span>/i)
    let location = addrMatch
      ? decodeHtmlEntities(addrMatch[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()) || "Rússia"
      : "Rússia"
    if (!location.toLowerCase().includes("россия") && !location.toLowerCase().includes("russia") && !location.toLowerCase().includes("rússia")) {
      location = `${location}, Rússia`
    }

    const workplace: "remote" | "hybrid" | "on-site" = block.includes("vacancy-label-work-schedule-remote")
      ? "remote"
      : detectWorkplace(title, location, block)

    let seniority: string | null = null
    if (block.includes("vacancy-serp__vacancy-work-experience-noExperience")) {
      seniority = "Júnior"
    } else if (block.includes("vacancy-serp__vacancy-work-experience-between1And3")) {
      seniority = "Pleno"
    } else if (
      block.includes("vacancy-serp__vacancy-work-experience-between3And6") ||
      block.includes("vacancy-serp__vacancy-work-experience-moreThan6")
    ) {
      seniority = "Sênior"
    }

    const respMatch = block.match(/data-qa="vacancy-serp__vacancy_snippet_responsibility"[^>]*>([\s\S]*?)<\/div>/i)
    const reqMatch = block.match(/data-qa="vacancy-serp__vacancy_snippet_requirement"[^>]*>([\s\S]*?)<\/div>/i)
    const snippetParts = [respMatch?.[1], reqMatch?.[1]]
      .filter((s): s is string => Boolean(s))
      .map((s) => decodeHtmlEntities(s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()))
      .filter(Boolean)
    const description = snippetParts.length > 0 ? snippetParts.join(" — ") : title

    const signals: string[] = []
    if (workplace === "remote") signals.push("remote")
    const lowerBlock = block.toLowerCase()
    if (lowerBlock.includes("relocation") || lowerBlock.includes("релокац") || lowerBlock.includes("виза") || lowerBlock.includes("visa")) {
      signals.push("relocation")
    }

    results.push({
      id,
      title,
      company,
      location,
      date: new Date().toISOString().slice(0, 10),
      url: cleanUrl,
      deadline: null,
      contract: "Efetivo",
      workplace_type: workplace,
      seniority,
      salary,
      description,
      country_code: "RU",
      signals,
    })
  }

  return results
}
