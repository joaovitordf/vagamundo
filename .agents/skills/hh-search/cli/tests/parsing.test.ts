import { describe, expect, test } from "bun:test"
import { fileURLToPath } from "node:url"
import path from "node:path"
import { parseHHSearch } from "../src/helpers.ts"

const cliDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")

describe("hh-search CLI", () => {
  test("--help exibe uso e sai com código 0", () => {
    const proc = Bun.spawnSync([process.execPath, "run", "src/cli.ts", "--help"], {
      cwd: cliDir,
      stdout: "pipe",
      stderr: "pipe",
    })
    expect(proc.exitCode).toBe(0)
    const stdout = new TextDecoder().decode(proc.stdout)
    expect(stdout).toContain("hh-search")
    expect(stdout).toContain("--remote")
  })
})

describe("parseHHSearch", () => {
  test("extrai vaga do hh.ru, ignora links fora de /vacancy/ e deduplica", () => {
    const html = `
      <div class="serp-item">
        <a data-qa="serp-item__title" href="/employer/123">Ignored Link</a>
      </div>
      <div class="serp-item">
        <a data-qa="serp-item__title" href="/vacancy/556677?from=serp">ML Engineer (Remote)</a>
        <a data-qa="vacancy-serp__vacancy-employer" href="/employer/9">Yandex Cloud</a>
        <span data-qa="vacancy-serp__vacancy-compensation">от 250 000 ₽</span>
        <span data-qa="vacancy-serp__vacancy-address">Москва</span>
        <span>Виза и релокация возможны</span>
      </div>
      <div class="serp-item">
        <a data-qa="serp-item__title" href="https://hh.ru/vacancy/556677?query=ml">ML Engineer (Remote)</a>
      </div>
    `
    const rows = parseHHSearch(html)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      id: "hh-556677",
      title: "ML Engineer (Remote)",
      company: "Yandex Cloud",
      salary: "от 250 000 ₽",
      location: "Москва, Rússia",
      url: "https://hh.ru/vacancy/556677",
      workplace_type: "remote",
      country_code: "RU",
    })
    expect(rows[0].signals).toContain("remote")
    expect(rows[0].signals).toContain("relocation")
  })
})
