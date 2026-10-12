import { describe, expect, it } from "vitest"
import { displayDate, filterRecords, hasResearchText, modelName, percentage, recordKind, safeSourceUrl, selectRecord } from "./companyFormat"

describe("company evidence formatting", () => {
  it("separates pending data from real research without discarding ordinary prose", () => {
    expect(hasResearchText("COH is tracked from the StonksInHand database. Add announcements and analysis data to enrich this brief.")).toBe(false)
    expect(hasResearchText("Summary pending.")).toBe(false)
    expect(hasResearchText("No material change identified.")).toBe(true)
    expect(hasResearchText("Revenue analysis remains pending regulatory review.")).toBe(true)
    expect(modelName("/var/task/models/finbert")).toBe("FinBERT")
  })
  it("rejects executable and malformed source URLs while preserving HTTP originals", () => {
    expect(safeSourceUrl("javascript:alert(1)")).toBeNull()
    expect(safeSourceUrl("data:text/html,hello")).toBeNull()
    expect(safeSourceUrl("/local/path")).toBeNull()
    expect(safeSourceUrl(null)).toBeNull()
    expect(safeSourceUrl("https://example.com/filing?company=BHP")).toBe("https://example.com/filing?company=BHP")
  })
  it("reports missing and invalid dates without throwing", () => {
    expect(displayDate(null)).toBe("Date unavailable")
    expect(displayDate("not-a-date")).toBe("Date unavailable")
    expect(displayDate("2026-10-12T00:00:00Z")).toContain("2026")
  })
  it("keeps zero model confidence distinct from absent confidence", () => {
    expect(percentage(0)).toBe("0%")
    expect(percentage(null)).toBe("Unavailable")
    expect(percentage(undefined)).toBe("Unavailable")
    expect(percentage(0.873)).toBe("87%")
  })
})

describe("source library selection", () => {
  const data = [
    { title: "Annual report", source_type: "asx_filing", about: "Copper operation", changed: "Production increased" },
    { title: "Annual report", source_type: "news", source_name: "Publisher", matters: "Cost sensitivity" },
    { title: "Discussion", source_type: "public_discussion", about: "Copper demand" },
  ]
  it("searches research context and distinguishes source families", () => {
    expect(recordKind(data[0])).toBe("Official filing")
    for (const source_type of ["bluesky", "mastodon", "blog"]) expect(recordKind({ source_type })).toBe("Public discussion")
    expect(filterRecords(data, " COPPER ", "all").map((item) => item.id)).toEqual([0, 2])
    expect(filterRecords(data, "cost", "Publisher news").map((item) => item.id)).toEqual([1])
    expect(filterRecords(data, "copper", "Publisher news")).toEqual([])
  })
  it("preserves record identity through filters and server-order reversal", () => {
    const all = filterRecords(data, "", "all")
    expect(selectRecord(all, 1)?.record).toBe(data[1])
    const reversed = filterRecords(data, "", "all", "oldest")
    expect(reversed.map((item) => item.id)).toEqual([2, 1, 0])
    expect(selectRecord(reversed, 1)?.record).toBe(data[1])
    expect(selectRecord(filterRecords(data, "copper", "all"), 1)?.record).toBe(data[0])
    expect(selectRecord([], 1)).toBeNull()
  })
})
