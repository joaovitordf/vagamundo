// Fonte de dados: o Portal Gupy (portal.gupy.io), o agregador público das vagas
// que as empresas publicam no ATS da Gupy.

import {
  decodeHtmlEntities,
  foldAccents,
  createHelpers,
  type JobResult,
} from "../../../_portal-kit/src/helpers.js"

export { decodeHtmlEntities, foldAccents, type JobResult }

export function cleanHtml(html: string | null | undefined): string | null {
  if (!html) return null
  const withBreaks = html
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\s*li[^>]*>/gi, "\n- ")
    .replace(/<\/(p|li|ul|ol|div|h\d)>/gi, "\n")
  const text = decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, " "))
    .replace(/ /g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\n+- /g, "\n- ")
    .replace(/^- \n/gm, "")
    .trim()
  return text || null
}

export const PORTAL_URL = "https://portal.gupy.io"
export const SEARCH_PATH = "/api/job-search/jobs"
export const GUPY_DOMAIN_URL = "https://gupy.io"
const GUPY_DOMAIN = new URL(GUPY_DOMAIN_URL).hostname

const UA = "Mozilla/5.0 (compatible; gupy-cli/1.0)"

const h = createHelpers({
  portal: "a Gupy",
  ua: UA,
  timeoutMs: 15000,
})

export const { writeError, retryAfterMs, httpGet } = h

// ---------------------------------------------------------------------------
// Vocabulários
// ---------------------------------------------------------------------------

/** Regime de contratação: apelido aceito em --type -> código da Gupy. */
export const CONTRACT_TYPES: Record<string, string> = {
  clt: "vacancy_type_effective",
  efetivo: "vacancy_type_effective",
  pj: "vacancy_legal_entity",
  estagio: "vacancy_type_internship",
  trainee: "vacancy_type_trainee",
  aprendiz: "vacancy_type_apprentice",
  temporario: "vacancy_type_temporary",
  terceiro: "vacancy_type_outsource",
  autonomo: "vacancy_type_autonomous",
  freelancer: "vacancy_type_freelancer",
  intermitente: "vacancy_type_intermittent",
  associado: "vacancy_type_associate",
  docente: "vacancy_type_lecturer",
  voluntario: "vacancy_type_volunteer",
  "banco-de-talentos": "vacancy_type_talent_pool",
  "summer-job": "vacancy_type_summer",
}

/** Código da Gupy -> rótulo legível (o mesmo texto que o portal mostra). */
export const CONTRACT_LABELS: Record<string, string> = {
  vacancy_type_effective: "CLT (efetivo)",
  vacancy_legal_entity: "PJ (pessoa jurídica)",
  vacancy_type_internship: "Estágio",
  vacancy_type_trainee: "Trainee",
  vacancy_type_apprentice: "Jovem aprendiz",
  vacancy_type_temporary: "Temporário",
  vacancy_type_outsource: "Terceirizado",
  vacancy_type_autonomous: "Autônomo",
  vacancy_type_freelancer: "Freelancer",
  vacancy_type_intermittent: "Intermitente",
  vacancy_type_associate: "Associado",
  vacancy_type_lecturer: "Docente",
  vacancy_type_volunteer: "Voluntário",
  vacancy_type_talent_pool: "Banco de talentos",
  vacancy_type_summer: "Summer job",
  vacancy_type_parter: "Sócio",
}

/** Modelo de trabalho: valor aceito em --remote -> valor da Gupy. */
export const WORKPLACE_TYPES: Record<string, string> = {
  remote: "remote",
  remoto: "remote",
  hybrid: "hybrid",
  hibrido: "hybrid",
  onsite: "on-site",
  "on-site": "on-site",
  presencial: "on-site",
}

const WORKPLACE_LABELS: Record<string, string> = { remote: "Remoto", hybrid: "Híbrido", "on-site": "Presencial" }

/** UF -> nome do estado como a Gupy grava (o filtro `state` usa o nome completo). */
export const UF_NAMES: Record<string, string> = {
  AC: "Acre", AL: "Alagoas", AP: "Amapá", AM: "Amazonas", BA: "Bahia", CE: "Ceará",
  DF: "Distrito Federal", ES: "Espírito Santo", GO: "Goiás", MA: "Maranhão",
  MT: "Mato Grosso", MS: "Mato Grosso do Sul", MG: "Minas Gerais", PA: "Pará",
  PB: "Paraíba", PR: "Paraná", PE: "Pernambuco", PI: "Piauí", RJ: "Rio de Janeiro",
  RN: "Rio Grande do Norte", RS: "Rio Grande do Sul", RO: "Rondônia", RR: "Roraima",
  SC: "Santa Catarina", SP: "São Paulo", SE: "Sergipe", TO: "Tocantins",
}

const NAME_TO_UF: Record<string, string> = Object.fromEntries(
  Object.entries(UF_NAMES).map(([uf, name]) => [foldAccents(name), uf]),
)

/** Aceita "SP", "sp", "São Paulo" ou "sao paulo"; devolve o nome oficial ou null. */
export function resolveState(input: string): string | null {
  const raw = input.trim()
  const uf = raw.toUpperCase()
  if (UF_NAMES[uf]) return UF_NAMES[uf]
  const byName = NAME_TO_UF[foldAccents(raw)]
  return byName ? UF_NAMES[byName] : null
}

/** "São Paulo" -> "SP" (null se não for um estado conhecido). */
export function stateToUf(state: string | null | undefined): string | null {
  if (!state) return null
  return NAME_TO_UF[foldAccents(state)] ?? null
}

// ---------------------------------------------------------------------------
// Formatos de dados
// ---------------------------------------------------------------------------

/** Uma vaga como a busca do portal devolve (só os campos que esta CLI lê). */
export interface GupySearchJob {
  id: number
  name: string
  description?: string | null
  careerPageName?: string | null
  type?: string | null
  publishedDate?: string | null
  applicationDeadline?: string | null
  workplaceType?: string | null
  city?: string | null
  state?: string | null
  jobUrl?: string | null
  disabilities?: boolean | null
}

export interface GupySearchResponse {
  data: GupySearchJob[]
  pagination?: { total?: number; limit?: number; offset?: number }
}

/** A parte AAAA-MM-DD de um carimbo ISO, ou null. */
export function contractDate(value: string | null | undefined): string | null {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(value ?? "")
  return m ? m[1] : null
}

/** "Cidade, UF", "Remoto" ou o que houver; null quando nada for conhecido. */
export function formatLocation(
  city: string | null | undefined,
  state: string | null | undefined,
  workplaceType: string | null | undefined,
): string | null {
  const uf = stateToUf(state) ?? (state || null)
  const place = [city || null, uf].filter(Boolean).join(", ")
  const mode = workplaceType ? WORKPLACE_LABELS[workplaceType] : undefined
  if (place && mode && mode !== "Presencial") return `${place} (${mode})`
  if (place) return place
  return mode ?? null
}

/**
 * URL canônica da vaga: https://<empresa>.gupy.io/jobs/<id>. A busca devolve
 * `jobUrl` no formato /job/<base64>?jobBoardSource=gupy_portal; o subdomínio
 * vem de lá. A forma canônica é estável e é a mesma que a página declara como
 * <link rel=canonical>, então a deduplicação do /scrape não se confunde.
 */
export function canonicalJobUrl(jobUrl: string | null | undefined, id: number | string): string | null {
  const sub = companySubdomain(jobUrl)
  return sub ? `https://${sub}.${GUPY_DOMAIN}/jobs/${id}` : null
}

/** Subdomínio da empresa numa URL *.gupy.io, ou null se não for uma página de carreira. */
export function companySubdomain(url: string | null | undefined): string | null {
  if (!url) return null
  let parsed: URL
  try {
    parsed = new URL(/^https?:\/\//i.test(url) ? url : `https://${url}`)
  } catch {
    return null
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null
  const host = parsed.hostname.toLowerCase()
  const suffix = `.${GUPY_DOMAIN}`
  if (!host.endsWith(suffix)) return null
  const sub = host.slice(0, -suffix.length)
  if (!/^[a-z0-9][a-z0-9-]*$/.test(sub)) return null
  if (["portal", "login", "api", "www", "attachments", "suporte-candidatos", "pravoce"].includes(sub)) return null
  return sub
}

/** Converte uma vaga da busca para o formato do contrato. */
export function toResult(j: GupySearchJob): JobResult {
  const code = j.type || null
  return {
    id: String(j.id),
    title: decodeHtmlEntities(j.name || "").replace(/\s+/g, " ").trim() || "(sem título)",
    company: j.careerPageName?.trim() || null,
    location: formatLocation(j.city, j.state, j.workplaceType),
    date: contractDate(j.publishedDate),
    url: canonicalJobUrl(j.jobUrl, j.id),
    deadline: contractDate(j.applicationDeadline),
    contract: code ? (CONTRACT_LABELS[code] ?? code) : null,
    contract_code: code,
    workplace_type: j.workplaceType || null,
    city: j.city || null,
    state: j.state || null,
    pcd: j.disabilities === true,
    description: cleanHtml(j.description),
  }
}

// ---------------------------------------------------------------------------
// Detalhe
// ---------------------------------------------------------------------------

export interface GupyDetailJob {
  id: number
  name: string
  description?: string | null
  responsibilities?: string | null
  prerequisites?: string | null
  relevantExperiences?: string | null
  addressCity?: string | null
  addressState?: string | null
  addressStateShortName?: string | null
  addressLine?: string | null
  jobType?: string | null
  workplaceType?: string | null
  publishedAt?: string | null
  registerEndDate?: string | null
  expiresAt?: string | null
  handicapped?: boolean | null
  jobSteps?: Array<{ name?: string | null }> | null
  careerPage?: { name?: string | null } | null
}

export interface JobDetailResult extends JobResult {
  address: string | null
  responsibilities: string | null
  requirements: string | null
  additional_info: string | null
  steps: string[]
}

/** Lê o JSON do bloco <script id="__NEXT_DATA__"> e devolve `props.pageProps.job`. */
export function parseDetailPage(html: string): GupyDetailJob | null {
  const m = /<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/.exec(html)
  if (!m) return null
  let data: unknown
  try {
    data = JSON.parse(m[1])
  } catch {
    return null
  }
  const job = (data as { props?: { pageProps?: { job?: GupyDetailJob } } })?.props?.pageProps?.job
  return job && typeof job === "object" && job.id != null ? job : null
}

export function toDetail(j: GupyDetailJob, subdomain: string): JobDetailResult {
  const code = j.jobType || null
  return {
    id: String(j.id),
    title: decodeHtmlEntities(j.name || "").replace(/\s+/g, " ").trim() || "(sem título)",
    company: j.careerPage?.name?.trim() || null,
    location: formatLocation(j.addressCity, j.addressState, j.workplaceType),
    date: contractDate(j.publishedAt),
    url: `https://${subdomain}.${GUPY_DOMAIN}/jobs/${j.id}`,
    deadline: contractDate(j.registerEndDate ?? j.expiresAt),
    contract: code ? (CONTRACT_LABELS[code] ?? code) : null,
    contract_code: code,
    workplace_type: j.workplaceType || null,
    city: j.addressCity || null,
    state: j.addressState || null,
    pcd: j.handicapped === true,
    address: j.addressLine?.trim() || null,
    description: cleanHtml(j.description),
    responsibilities: cleanHtml(j.responsibilities),
    requirements: cleanHtml(j.prerequisites),
    additional_info: cleanHtml(j.relevantExperiences),
    steps: (j.jobSteps ?? []).map((s) => s?.name?.trim() || "").filter(Boolean),
  }
}

export function parseJobUrl(input: string): { subdomain: string; id: string } | null {
  const trimmed = input.trim()
  const sub = companySubdomain(trimmed)
  if (!sub) return null
  const parsed = new URL(/^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`)
  const path = parsed.pathname.replace(/\/+$/, "")
  const direct = /^(?:\/[a-z]{2}(?:-[a-z]{2})?)?\/jobs\/(\d+)$/i.exec(path)
  if (direct) return { subdomain: sub, id: direct[1] }
  const encoded = /^(?:\/[a-z]{2}(?:-[a-z]{2})?)?\/job\/([A-Za-z0-9_+=-]+)$/i.exec(path)
  if (encoded) {
    try {
      const json = JSON.parse(Buffer.from(encoded[1].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"))
      const id = json?.jobId
      if (Number.isInteger(id) && id > 0) return { subdomain: sub, id: String(id) }
    } catch {
      return null
    }
  }
  return null
}
