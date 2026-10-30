import type { JobPostingLD } from "./types.js"

export function numericEntity(cp: number): string {
  return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
}

export function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, dec) => numericEntity(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => numericEntity(parseInt(hex, 16)))
    .replace(/&amp;/g, "&")
}

export function tidyPunctuation(text: string): string {
  return text.replace(/[ \t]+([,.;:!?)\]])/g, "$1").replace(/([(\[])[ \t]+/g, "$1")
}

export function inlineText(html: string | null | undefined): string | null {
  if (!html) return null
  const text = tidyPunctuation(decodeHtmlEntities(html.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ")).trim()
  return text || null
}

export function cleanHtml(html: string | null | undefined): string | null {
  if (!html) return null
  const withBreaks = html
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\s*li[^>]*>/gi, "\n- ")
    .replace(/<\/(p|li|ul|ol|div|h\d)>/gi, "\n")
  const text = decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, " "))
    .replace(/ /g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\n+- /g, "\n- ")
    .replace(/^- \n/gm, "")
  return tidyPunctuation(text).trim() || null
}

export function foldAccents(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim()
}

export function titleMatches(title: string, query: string): boolean {
  const t = foldAccents(title)
  return foldAccents(query)
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => new RegExp(`(^|[^a-z0-9])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(t))
}

export function readJobPosting(html: string): JobPostingLD | null {
  const re = /<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi
  for (const m of html.matchAll(re)) {
    let data: unknown
    try {
      data = JSON.parse(m[1])
    } catch {
      try {
        data = JSON.parse(m[1].replace(/[\u0000-\u001f]/g, " "))
      } catch {
        continue
      }
    }
    const graph = (data as { "@graph"?: unknown[] } | null)?.["@graph"]
    const items = Array.isArray(data) ? data : Array.isArray(graph) ? graph : [data]
    for (const item of items) {
      if (item && typeof item === "object" && (item as { "@type"?: string })["@type"] === "JobPosting") {
        return item as JobPostingLD
      }
    }
  }
  return null
}

export function ldLocation(ld: JobPostingLD): string | null {
  const loc = Array.isArray(ld.jobLocation) ? ld.jobLocation[0] : ld.jobLocation
  const city = loc?.address?.addressLocality?.trim()
  const uf = loc?.address?.addressRegion?.trim()
  const place = [city && !/n[ãa]o informad/i.test(city) ? city : null, uf || null].filter(Boolean).join(", ")
  return place || null
}

