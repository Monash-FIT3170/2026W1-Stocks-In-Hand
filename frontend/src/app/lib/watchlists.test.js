import { describe, expect, it } from "vitest"
import { buildWatchlistCreatePayload, watchlistCard } from "./watchlists"

const NOW = new Date("2040-01-10T12:00:00Z")

describe("buildWatchlistCreatePayload", () => {
  it("includes the authenticated investor required by the API schema", () => {
    expect(buildWatchlistCreatePayload("investor-123")).toEqual({
      investor_id: "investor-123",
      name: "My Watchlist",
    })
  })

  it("refuses to create an ownerless watchlist", () => {
    expect(() => buildWatchlistCreatePayload(null)).toThrow(
      "Could not identify the signed-in investor."
    )
  })
})

describe("watchlistCard", () => {
  it("shows a positive latest signal in green", () => {
    const card = watchlistCard({ sector: "Financials", latest_signal: { sentiment_label: "positive" } }, NOW)

    expect(card.status).toBe("Positive Sentiment")
    expect(card.tone).toBe("green")
  })

  it("shows a negative latest signal in red", () => {
    expect(watchlistCard({ latest_signal: { sentiment_label: "negative" } }, NOW)).toMatchObject({
      status: "Negative Sentiment",
      tone: "red",
    })
  })

  it("monitors the sector of a company with no signal yet", () => {
    expect(watchlistCard({ sector: "Materials", latest_signal: null }, NOW)).toMatchObject({
      status: "Materials Monitoring",
      tone: "orange",
    })
    expect(watchlistCard({}, NOW).status).toBe("Monitoring")
  })

  it("cuts a long brief to 147 characters and an ellipsis", () => {
    const brief = "A".repeat(151)

    expect(watchlistCard({ brief }, NOW).brief).toBe(`${"A".repeat(147)}…`)
    expect(watchlistCard({ brief: "Short brief." }, NOW).brief).toBe("Short brief.")
    expect(watchlistCard({ brief: null }, NOW).brief).toBeNull()
  })

  it("dates the last brief relative to now", () => {
    const lastBrief = (value) => watchlistCard({ last_brief_at: value }, NOW).lastBrief

    expect(lastBrief("2040-01-10T01:00:00Z")).toBe("Today")
    expect(lastBrief("2040-01-09T06:00:00Z")).toBe("Yesterday")
    expect(lastBrief("2040-01-03T12:00:00Z")).toBe("7 days ago")
    expect(lastBrief(null)).toBe("Not available")
    expect(lastBrief("not a date")).toBe("Not available")
  })
})
