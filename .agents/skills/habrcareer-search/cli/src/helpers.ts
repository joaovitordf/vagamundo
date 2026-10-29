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
        if (attempt === maxRetries) throw new Error(`career.habr.ru retornou status ${res.status}`)
        await new Promise((r) => setTimeout(r, delay))
        delay *= 2
        continue
      }
      if (!res.ok) throw new Error(`career.habr.ru retornou status ${res.status}: ${res.statusText}`)
      return await res.text()
    } catch (err: any) {
      if (attempt === maxRetries) throw err
      await new Promise((r) => setTimeout(r, delay))
      delay *= 2
    }
  }
  throw new Error("Falha ao conectar com career.habr.ru após múltiplas tentativas")
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

export function detectWorkplace(text: string): "remote" | "hybrid" | "on-site" {
  const lower = text.toLowerCase()
  if (lower.includes("remote") || lower.includes("удален") || lower.includes("дистанцион")) {
    return "remote"
  }
  if (lower.includes("hybrid") || lower.includes("гибрид")) {
    return "hybrid"
  }
  return "on-site"
}

export function parseHabrSearch(html: string): JobResult[] {
  const results: JobResult[] = []
  const seenUrls = new Set<string>()

  // Regex para encontrar blocos de card
  const titleRegex = /<a[^>]*class="[^"]*vacancy-card__title-link[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi
  let m: RegExpExecArray | null

  while ((m = titleRegex.exec(html)) !== null) {
    let rawUrl = m[1]
    if (rawUrl.startsWith("/")) rawUrl = `https://career.habr.ru${rawUrl}`
    const cleanUrl = rawUrl.split("?")[0]
    if (seenUrls.has(cleanUrl)) continue
    seenUrls.add(cleanUrl)

    const idMatch = cleanUrl.match(/\/vacancies\/(\d+)/)
    const id = idMatch ? `habr-${idMatch[1]}` : `habr-${Date.now()}-${results.length}`
    const title = decodeHtmlEntities(m[2].replace(/<[^>]+>/g, "").trim())

    const idx = m.index
    const block = html.slice(Math.max(0, idx - 400), Math.min(html.length, idx + 2500))

    // Empresa
    const empMatch = block.match(/class="link-comp[^"]*"[^>]*>([\s\S]*?)<\/a>/i)
    const company = empMatch ? decodeHtmlEntities(empMatch[1].replace(/<[^>]+>/g, "").trim()) : null

    // Salário
    const salMatch = block.match(/class="[^"]*vacancy-card__salary[^"]*"[^>]*>([\s\S]*?)<\/div>/i)
    let salary = salMatch ? decodeHtmlEntities(salMatch[1].replace(/<[^>]+>/g, " ").trim()) : null
    if (salary && (salary.includes("Зарплата не указана") || salary.includes("Похожие специалисты"))) {
      const pred = salary.match(/Похожие специалисты получают ([^<]+)/i)
      salary = pred ? `~${pred[1].trim()}` : null
    }

    // Data
    const dateMatch = block.match(/datetime="([^"]+)"/i)
    const date = dateMatch ? dateMatch[1].slice(0, 10) : new Date().toISOString().slice(0, 10)

    // Meta (chips com local e modalidade)
    const workplace = detectWorkplace(block)
    const signals: string[] = []
    if (workplace === "remote") signals.push("remote")
    const lowerBlock = block.toLowerCase()
    if (lowerBlock.includes("relocation") || lowerBlock.includes("релокац") || lowerBlock.includes("виза") || lowerBlock.includes("visa")) {
      signals.push("relocation")
    }

    let location = workplace === "remote" ? "Remoto (Rússia)" : "Rússia"
    if (lowerBlock.includes("москва") || lowerBlock.includes("moscow")) location = "Moscou, Rússia"
    else if (lowerBlock.includes("санкт-петербург") || lowerBlock.includes("saint petersburg")) location = "São Petersburgo, Rússia"

    results.push({
      id,
      title,
      company,
      location,
      date,
      url: cleanUrl,
      deadline: null,
      contract: "Efetivo",
      workplace_type: workplace,
      seniority: null,
      salary,
      description: title,
      country_code: "RU",
      signals
    })
  }

  return results
}

