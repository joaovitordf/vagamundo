import { describe, expect, test } from "bun:test"
import {
  brDate,
  cleanHtml,
  createHelpers,
  decodeHtmlEntities,
  formatSalary,
  relativeDate,
  titleMatches,
  withinJobAge,
  type JobResult,
} from "../src/index.js"

describe("portal-kit helpers", () => {
  const now = new Date("2026-10-20T12:00:00Z")

  test("relative and absolute dates", () => {
    expect(relativeDate("Hoje", now)).toBe("2026-10-20")
    expect(relativeDate("Ontem", now)).toBe("2026-10-19")
    expect(relativeDate("Há 3 dias", now)).toBe("2026-10-17")
    expect(brDate("25/12/2026")).toBe("2026-12-25")
  })

  test("salary formatting", () => {
    expect(formatSalary(5000, 8000)).toContain("5.000,00 a R$ 8.000,00")
  })

  test("cleanHtml", () => {
    expect(cleanHtml("<p>Olá&nbsp;<strong>Mundo</strong></p>")).toBe("Olá Mundo")
  })

  test("titleMatches", () => {
    expect(titleMatches("Desenvolvedor Angular Pleno", "angular")).toBe(true)
    expect(titleMatches("Desenvolvedor Python", "angular")).toBe(false)
  })

  test("createHelpers factory", () => {
    const h = createHelpers({ portal: "Portal Teste", ua: "teste-cli/1.0" })
    expect(h.PORTAL).toBe("Portal Teste")
    expect(h.UA).toBe("teste-cli/1.0")
    expect(typeof h.httpGet).toBe("function")
  })
})

