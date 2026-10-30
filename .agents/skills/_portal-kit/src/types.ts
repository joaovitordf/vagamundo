export interface PortalConfig {
  portal: string
  ua: string
  timeoutMs?: number
  retryBudgetMs?: number
}

export interface JobResult {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string | null
  deadline: string | null
  contract?: string | null
  contract_code?: string | null
  workplace_type?: "remote" | "hybrid" | "on-site" | string | null
  seniority?: string | null
  salary?: string | null
  city?: string | null
  state?: string | null
  pcd?: boolean
  description?: string | null
  [key: string]: unknown
}

export interface JobPostingLD {
  title?: string
  description?: string
  datePosted?: string
  validThrough?: string
  employmentType?: string | string[]
  jobLocationType?: string
  identifier?: { value?: string | number }
  hiringOrganization?: { name?: string }
  jobLocation?:
    | { address?: { addressLocality?: string; addressRegion?: string } }
    | Array<{ address?: { addressLocality?: string; addressRegion?: string } }>
  baseSalary?: { value?: { minValue?: number; maxValue?: number; value?: number } }
  [key: string]: unknown
}

export interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

export interface SearchResultMeta {
  count: number
  page: number
  total: number
}

export interface SearchResponse {
  meta: SearchResultMeta
  results: JobResult[]
}

