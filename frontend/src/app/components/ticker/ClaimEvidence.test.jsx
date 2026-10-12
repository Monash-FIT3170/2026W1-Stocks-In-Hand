import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest"
import { ClaimEvidence } from "./ClaimEvidence"
import { CategorySentiment } from "./CategorySentiment"
import { ClarityLayer } from "./ClarityLayer"
import { AnnouncementCard } from "../announcements/AnnouncementCard"

beforeEach(() => vi.stubGlobal("React", React))
afterEach(() => vi.unstubAllGlobals())

const claim = {
  id: "artifact:confirmed_facts:0", field: "confirmed_facts", index: 0,
  text: "Revenue rose.", status: "quoted",
  source: { title: "Results", url: "https://example.test/report.pdf" },
  evidence: [{ quote: "Revenue <increased> by 12%.", start_char: 0 }],
}
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props))

describe("per-claim source quotations", () => {
  it("provides an expandable exact quotation and original link, escaping source text", () => {
    const html = render(ClaimEvidence, { claim })
    expect(html).toContain("<details")
    expect(html).toContain("View source quotation")
    expect(html).toContain("Revenue &lt;increased&gt; by 12%.")
    expect(html).toContain('href="https://example.test/report.pdf"')
    expect(html).toContain('rel="noopener noreferrer"')
  })
  it("shows missing quotations explicitly without hiding the source", () => {
    const html = render(ClaimEvidence, { claim: { ...claim, status: "quotation_unavailable", evidence: [] } })
    expect(html).toContain("No source quotation available")
    expect(html).toContain("Open original source")
    expect(html).not.toContain("<blockquote")
  })
  it("does not turn an unsafe link into a quotation control", () => {
    const html = render(ClaimEvidence, { claim: { ...claim, source: { url: "javascript:alert(1)" } } })
    expect(html).toContain("Original source link unavailable")
    expect(html).not.toContain("href=")
    expect(html).not.toContain("<blockquote")
  })
  it("traces forecasts separately from factual claims", () => {
    const forecast = { ...claim, id: "artifact:speculation:0", field: "speculation", text: "Growth may continue.", evidence: [{ quote: "We expect further growth." }] }
    const html = render(ClarityLayer, {
      clarity: { is_classified: true, confirmed_facts: [claim.text], speculation: [forecast.text] },
      claims: [claim, forecast],
    })
    expect(html.match(/View source quotation/g)).toHaveLength(2)
    expect(html).toContain("We expect further growth.")
    expect(html).toContain("Reported facts")
    expect(html).toContain("Speculation")
  })
  it("does not lend quotations to different displayed announcement wording", () => {
    const html = render(AnnouncementCard, { item: {
      ticker: "BHP", title: "Results", about: "Revenue fell.", changed: "Revenue rose.", matters: "Investors may monitor growth.",
      claims: [{ ...claim, field: "changed" }], url: claim.source.url,
    } })
    expect(html.match(/View source quotation/g)).toHaveLength(1)
    expect(html.match(/No source quotation available/g)).toHaveLength(2)
  })
})


it("carries source claims through aggregated category cards", () => {
  const html = render(CategorySentiment, { sentiment: {
    status: "partial", categories: { revenue: {
      available: true, sentiment_label: "positive", confidence_score: 0.9,
      summary: "Revenue grew across stored reports.", claims: [claim],
      sources: [{ ...claim.source, source_type: "asx_announcement" }],
    } },
  } })
  expect(html).toContain("Trace individual claims")
  expect(html).toContain("View source quotation")
  expect(html).toContain("Revenue &lt;increased&gt; by 12%.")
})
