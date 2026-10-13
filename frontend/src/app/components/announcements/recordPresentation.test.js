import { describe, expect, it } from "vitest"
import { companyRoute, groupByPublicationDate, meaningfulText, originalUrl, recordSources, sourceKind } from "./recordPresentation"

describe("market feed record presentation", () => {
  it("keeps generic market records out of unsupported company routes", () => {
    expect(companyRoute("ASX")).toBeNull()
    expect(companyRoute("ZZZ")).toBeNull()
    expect(companyRoute("coh")).toBe("/ticker/COH")
  })
  it("suppresses missing analysis and repeated titles without discarding factual text", () => {
    expect(meaningfulText("No impact summary available yet.")).toBe("")
    expect(meaningfulText("Ceasing to be a substantial holder", "Ceasing to be a substantial holder")).toBe("")
    expect(meaningfulText("No material change identified.")).toBe("No material change identified.")
  })
  it("rejects unsafe originals and deduplicates direct/citation URLs", () => {
    expect(originalUrl("javascript:alert(1)")).toBeNull()
    const result = recordSources({ url: "https://example.com/original", sources: [null, { url: "https://example.com/original" }, { url: "https://example.com/other" }, { url: "https://example.com/other" }] })
    expect(result.primary).toBe("https://example.com/original")
    expect(result.additional).toHaveLength(1)
    expect(recordSources({ url: "broken", sources: [{ url: "https://example.com/original" }] }).primary).toBe("https://example.com/original")
  })
  it("distinguishes official records, publisher coverage and public discussion", () => {
    expect(sourceKind("asx_announcement")).toBe("Official filing")
    expect(sourceKind("news")).toBe("Publisher news")
    expect(sourceKind("reddit_post")).toBe("Public discussion")
  })
  it("groups records on Sydney publication dates across UTC midnight without losing records", () => {
    const records = [
      { id: 1, published_at: "2026-10-12T14:30:00Z" },
      { id: 2, published_at: "2026-10-12T01:00:00Z" },
      { id: 3, published_at: "2026-10-13T00:15:00Z" },
      { id: 4, published_at: "invalid" },
      { id: 5, published_at: null },
    ]
    const groups = groupByPublicationDate(records)
    expect(groups.map((group) => group.label)).toEqual(["13 October 2026", "12 October 2026", "Date unavailable"])
    expect(groups[0].items.map((item) => item.id)).toEqual([1, 3])
    expect(groups.flatMap((group) => group.items).map((item) => item.id).sort()).toEqual([1, 2, 3, 4, 5])
  })
})
