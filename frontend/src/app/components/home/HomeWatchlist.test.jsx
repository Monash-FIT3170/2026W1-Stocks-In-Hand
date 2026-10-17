import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, test } from "vitest"
import { HomeWatchlist } from "./HomeWatchlist"

const investor = { id: "investor", username: "Jordan" }
const company = {
  ticker_id: "bhp", symbol: "BHP", company_name: "BHP Group", exchange: "ASX",
  sector: "Materials", brief: "Copper production increased.",
  last_brief_at: "2040-01-02T00:00:00Z",
  latest_signal: { sentiment_label: "positive" },
}

function render(props = {}) {
  return renderToStaticMarkup(<HomeWatchlist investor={investor} companies={[]} isLoading={false} error="" {...props} />)
}

describe("home watchlist", () => {
  test("does not expose saved companies after the session ends", () => {
    expect(render({ investor: null, companies: [company] })).toBe("")
  })

  test("shows saved company research and links to its brief", () => {
    const markup = render({ companies: [company] })
    expect(markup).toContain("My watchlist")
    expect(markup).toContain("BHP Group")
    expect(markup).toContain("ASX: BHP")
    expect(markup).toContain("Copper production increased.")
    expect(markup).toContain("Positive Sentiment")
    expect(markup).toContain('href="/ticker/BHP"')
    expect(markup).toContain('href="/watchlist"')
    expect(markup).not.toContain("No companies yet")
  })

  test("offers adding a company when the saved watchlist is empty", () => {
    const markup = render()
    expect(markup).toContain("No companies yet")
    expect(markup).toContain("Add company")
    expect(markup).not.toContain("BHP Group")
  })

  test("keeps loading and failed reads separate from an empty watchlist", () => {
    const loading = render({ isLoading: true })
    expect(loading).toContain('role="status"')
    expect(loading).toContain("Loading your watchlist")
    expect(loading).not.toContain("No companies yet")
    const failed = render({ error: "Watchlist unavailable", companies: [company] })
    expect(failed).toContain('role="alert"')
    expect(failed).toContain("Watchlist unavailable")
    expect(failed).toContain("Try again")
    expect(failed).not.toContain("No companies yet")
    expect(failed).not.toContain("BHP Group")
  })

  test("uses the monitoring state when research is not yet available", () => {
    const markup = render({ companies: [{ ...company, brief: null, last_brief_at: null, latest_signal: null }] })
    expect(markup).toContain("Materials Monitoring")
    expect(markup).toContain("Last brief: Not available")
    expect(markup).not.toContain("Copper production increased.")
  })
})
