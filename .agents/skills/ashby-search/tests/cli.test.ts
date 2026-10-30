import { describe, expect, it } from "bun:test"
import { spawnSync } from "child_process"
import { resolve } from "path"

const CLI_PATH = resolve(__dirname, "../cli/src/cli.ts")

describe("ashby-search CLI", () => {
  it("prints help when called with --help", () => {
    const res = spawnSync("bun", ["run", CLI_PATH, "--help"], { encoding: "utf-8" })
    expect(res.status).toBe(0)
    expect(res.stdout).toContain("ashby-cli")
  })

  it("fails when query is missing", () => {
    const res = spawnSync("bun", ["run", CLI_PATH, "search"], { encoding: "utf-8" })
    expect(res.status).toBe(1)
  })
})

