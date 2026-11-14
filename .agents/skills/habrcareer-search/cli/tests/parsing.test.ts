import { describe, expect, test } from "bun:test"
import { fileURLToPath } from "node:url"
import path from "node:path"
import { parseHabrSearch } from "../src/helpers.ts"

const cliDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")

describe("habrcareer-search CLI", () => {
  test("--help exibe uso e sai com código 0", () => {
    const proc = Bun.spawnSync([process.execPath, "run", "src/cli.ts", "--help"], {
      cwd: cliDir,
      stdout: "pipe",
      stderr: "pipe",
    })
    expect(proc.exitCode).toBe(0)
    const stdout = new TextDecoder().decode(proc.stdout)
    expect(stdout).toContain("habrcareer-search")
    expect(stdout).toContain("--remote")
  })
})

describe("parseHabrSearch", () => {
  test("extrai vaga com empresa, data, salário, remoto e relocation e deduplica URLs", () => {
    const html = `
      <div class="vacancy-card">
        <a class="vacancy-card__title-link" href="/vacancies/90123?ref=list">Senior Python Engineer</a>
        <a class="link-comp" href="/companies/acme">Acme Tech</a>
        <div class="vacancy-card__salary">от 300 000 ₽</div>
        <time datetime="2026-10-18T10:00:00Z"></time>
        <span>Москва • Можно удаленно • Relocation available</span>
      </div>
      <div class="vacancy-card">
        <a class="vacancy-card__title-link" href="/vacancies/90123?duplicate=1">Senior Python Engineer</a>
      </div>
    `
    const rows = parseHabrSearch(html)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      id: "habr-90123",
      title: "Senior Python Engineer",
      company: "Acme Tech",
      salary: "от 300 000 ₽",
      date: "2026-10-18",
      url: "https://career.habr.ru/vacancies/90123",
      location: "Moscou, Rússia",
      workplace_type: "remote",
      country_code: "RU",
    })
    expect(rows[0].signals).toContain("remote")
    expect(rows[0].signals).toContain("relocation")
  })

  test("descarta placeholder de salário e preserva estimativa de especialistas", () => {
    const noSalaryRows = parseHabrSearch(`
      <div class="vacancy-card">
        <a class="vacancy-card__title-link" href="/vacancies/111">Backend Go</a>
        <div class="vacancy-card__salary">Зарплата не указана</div>
      </div>
    `)
    expect(noSalaryRows).toHaveLength(1)
    expect(noSalaryRows[0].salary).toBeNull()

    const predictedRows = parseHabrSearch(`
      <div class="vacancy-card">
        <a class="vacancy-card__title-link" href="/vacancies/222">Data Engineer</a>
        <div class="vacancy-card__salary">Похожие специалисты получают от 200 000 ₽</div>
      </div>
    `)
    expect(predictedRows).toHaveLength(1)
    expect(predictedRows[0].salary).toBe("~от 200 000 ₽")
  })
})
