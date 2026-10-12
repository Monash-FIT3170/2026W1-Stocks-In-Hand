import { describe, expect, it } from "vitest"
import { findClaim, safeSourceUrl } from "./traceability"

describe("claim quotation matching", () => {
  const claims = [{ field: "about", text: "Revenue grew.", status: "quoted" }]
  it("only selects evidence for the displayed field and wording", () => {
    expect(findClaim(claims, "about", " Revenue grew. ")).toBe(claims[0])
    expect(findClaim(claims, "changed", "Revenue grew.")).toBeNull()
    expect(findClaim(claims, "about", "Revenue fell.")).toBeNull()
    expect(findClaim(undefined, "about", "Revenue grew.")).toBeNull()
  })
  it.each(["javascript:alert(1)", "//example.test", "https://user:secret@example.test", "https://example.test\n", null])("rejects unsafe source URL %s", (url) => {
    expect(safeSourceUrl(url)).toBeNull()
  })
  it("accepts HTTPS filings", () => {
    expect(safeSourceUrl("https://example.test/report.pdf")).toBe("https://example.test/report.pdf")
  })
})
