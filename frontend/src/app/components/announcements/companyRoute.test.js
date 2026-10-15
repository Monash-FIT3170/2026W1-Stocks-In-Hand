import { describe, expect, it, vi } from "vitest"

vi.mock("../../ticker/tickers.json", () => ({ default: ["ANZ", "NEWCO"] }))

const { companyRoute } = await import("./recordPresentation")

describe("company routes", () => {
  it("links exactly the tickers the catalogue deploys", () => {
    expect(companyRoute("newco")).toBe("/ticker/NEWCO")
    expect(companyRoute("ANZ")).toBe("/ticker/ANZ")
    expect(companyRoute("BHP")).toBeNull()
  })
})
