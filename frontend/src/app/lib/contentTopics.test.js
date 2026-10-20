import { describe, expect, it } from "vitest"
import { CONTENT_TOPICS, isContentTopic, recordTopics, topicFilterHref, topicLabel, trendLabel } from "./contentTopics"

describe("content topics", () => {
  it("names the five topics the backend tags", () => {
    expect(CONTENT_TOPICS.map((topic) => topic.id)).toEqual([
      "earnings_guidance",
      "litigation",
      "regulation",
      "product_launch",
      "macro_exposure",
    ])
    expect(isContentTopic("litigation")).toBe(true)
    expect(isContentTopic("astrology")).toBe(false)
  })

  it("labels known topics and shows an unknown identifier as words", () => {
    expect(topicLabel("earnings_guidance")).toBe("Earnings and guidance")
    expect(topicLabel("earnings_guidance", { short: true })).toBe("Earnings")
    expect(topicLabel("supply_chain")).toBe("Supply chain")
    expect(topicLabel(null)).toBe("")
  })

  it("keeps a record's topics in order without blanks or duplicates", () => {
    expect(recordTopics({ topics: ["regulation", "", "litigation", "regulation", 3] })).toEqual(["regulation", "litigation"])
    expect(recordTopics({})).toEqual([])
    expect(recordTopics(null)).toEqual([])
  })

  it("links only known topics to the feed filter", () => {
    expect(topicFilterHref("macro_exposure")).toBe("/announcements?topic=macro_exposure")
    expect(topicFilterHref("<script>")).toBe("/announcements")
  })

  it("describes every trend the API sends", () => {
    for (const trend of ["new", "rising", "steady", "falling", "quiet"]) expect(trendLabel(trend)).not.toBe("Trend unavailable")
    expect(trendLabel("sideways")).toBe("Trend unavailable")
  })
})
