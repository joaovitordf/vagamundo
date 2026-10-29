import { fetchHtml, cleanHtml, decodeHtmlEntities, detectWorkplace, type JobResult } from "../helpers.ts"

export async function runDetail(target: string): Promise<void> {
  let url = target.trim()
  if (/^\d+$/.test(url)) {
    url = `https://career.habr.ru/vacancies/${url}`
  } else if (!url.startsWith("http")) {
    url = `https://career.habr.ru/vacancies/${url.replace(/^habr-/, "")}`
  }

  const html = await fetchHtml(url)
  const idMatch = url.match(/\/vacancies\/(\d+)/)
  const id = idMatch ? `habr-${idMatch[1]}` : `habr-${Date.now()}`

  // Título
  const titleMatch = html.match(/class="page-title__title"[^>]*>([\s\S]*?)<\/h1>/i) || html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i)
  const title = titleMatch ? decodeHtmlEntities(titleMatch[1].replace(/<[^>]+>/g, "").trim()) : "Vaga Habr Career"

  // Empresa
  const empMatch = html.match(/class="company_name"[^>]*>([\s\S]*?)<\/a>/i) || html.match(/class="link-comp[^"]*"[^>]*>([\s\S]*?)<\/a>/i)
  const company = empMatch ? decodeHtmlEntities(empMatch[1].replace(/<[^>]+>/g, "").trim()) : null

  // Salário
  const salMatch = html.match(/class="basic-salary[^"]*"[^>]*>([\s\S]*?)<\/div>/i)
  const salary = salMatch ? decodeHtmlEntities(salMatch[1].replace(/<[^>]+>/g, " ").trim()) : null

  // Descrição
  const descMatch = html.match(/class="vacancy-description__text"[^>]*>([\s\S]*?)<\/div>/i) || html.match(/class="style-ugc"[^>]*>([\s\S]*?)<\/div>/i)
  const description = descMatch ? cleanHtml(descMatch[1]) : null

  // Local & Modalidade
  const workplace = detectWorkplace(`${title} ${html}`)
  const signals: string[] = []
  if (workplace === "remote") signals.push("remote")
  const lower = html.toLowerCase()
  if (lower.includes("relocation") || lower.includes("релокац") || lower.includes("виза") || lower.includes("visa")) {
    signals.push("relocation")
  }

  let location = workplace === "remote" ? "Remoto (Rússia)" : "Rússia"
  if (lower.includes("москва") || lower.includes("moscow")) location = "Moscou, Rússia"
  else if (lower.includes("санкт-петербург") || lower.includes("saint petersburg")) location = "São Petersburgo, Rússia"

  const result: JobResult = {
    id,
    title,
    company,
    location,
    date: new Date().toISOString().slice(0, 10),
    url,
    deadline: null,
    contract: "Efetivo",
    workplace_type: workplace,
    seniority: null,
    salary,
    description,
    country_code: "RU",
    signals
  }

  console.log(JSON.stringify(result, null, 2))
}

