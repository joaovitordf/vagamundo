import { fetchHtml, cleanHtml, decodeHtmlEntities, detectWorkplace, type JobResult } from "../helpers.ts"

export async function runDetail(target: string): Promise<void> {
  let url = target.trim()
  if (/^\d+$/.test(url)) {
    url = `https://hh.ru/vacancy/${url}`
  } else if (!url.startsWith("http")) {
    url = `https://hh.ru/vacancy/${url.replace(/^hh-/, "")}`
  }

  const html = await fetchHtml(url)
  const idMatch = url.match(/\/vacancy\/(\d+)/)
  const id = idMatch ? `hh-${idMatch[1]}` : `hh-${Date.now()}`

  // Título
  const titleMatch = html.match(/data-qa="vacancy-title"[^>]*>([\s\S]*?)<\/h1>/i) || html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i)
  const title = titleMatch ? decodeHtmlEntities(titleMatch[1].replace(/<[^>]+>/g, "").trim()) : "Vaga HeadHunter"

  // Empresa
  const empMatch = html.match(/data-qa="vacancy-company-name"[^>]*>([\s\S]*?)<\/a>/i) || html.match(/data-qa="vacancy-company-name"[^>]*>([\s\S]*?)<\/span>/i)
  const company = empMatch ? decodeHtmlEntities(empMatch[1].replace(/<[^>]+>/g, "").trim()) : null

  // Salário
  const salMatch = html.match(/data-qa="vacancy-salary"[^>]*>([\s\S]*?)<\/div>/i)
  const salary = salMatch ? decodeHtmlEntities(salMatch[1].replace(/<[^>]+>/g, "").trim()) : null

  // Descrição
  const descMatch = html.match(/data-qa="vacancy-description"[^>]*>([\s\S]*?)<\/div>/i)
  const description = descMatch ? cleanHtml(descMatch[1]) : null

  // Local
  const addrMatch = html.match(/data-qa="vacancy-view-location"[^>]*>([\s\S]*?)<\/span>/i) || html.match(/data-qa="vacancy-view-raw-address"[^>]*>([\s\S]*?)<\/span>/i)
  let location = addrMatch ? decodeHtmlEntities(addrMatch[1].replace(/<[^>]+>/g, "").trim()) : "Rússia"
  if (!location.toLowerCase().includes("россия") && !location.toLowerCase().includes("russia") && !location.toLowerCase().includes("rússia")) {
    location = `${location}, Rússia`
  }

  const workplace = detectWorkplace(title, location, description || "")
  const signals: string[] = []
  if (workplace === "remote") signals.push("remote")
  const lowerDesc = (description || "").toLowerCase()
  if (lowerDesc.includes("relocation") || lowerDesc.includes("релокац") || lowerDesc.includes("виза") || lowerDesc.includes("visa")) {
    signals.push("relocation")
  }

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

