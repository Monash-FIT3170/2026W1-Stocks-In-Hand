import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, test } from "vitest"

import { SourceLinks } from "./CompanyPrimitives"

describe("report source links", () => {
  test.each([true, false])("shows the exact document title and date with compact=%s", (compact) => {
    const markup = renderToStaticMarkup(<SourceLinks compact={compact} sources={[{
      title: "Company annual results 2026",
      label: "ASX Announcement",
      url: "https://example.test/results.pdf",
      published_at: "2026-10-01T12:00:00Z",
    }]} />)

    expect(markup).toMatch(/>Company annual results 2026<svg/)
    expect(markup).toContain('href="https://example.test/results.pdf"')
    expect(markup).toContain("1 Oct 2026")
    expect(markup).toContain('target="_blank" rel="noopener noreferrer"')
  })

  test("keeps a readable fallback when a legacy source has no title", () => {
    const markup = renderToStaticMarkup(<SourceLinks compact sources={[{
      label: "ASX Announcement", url: "https://example.test/results.pdf",
    }]} />)

    expect(markup).toMatch(/>ASX announcement<svg/)
    expect(markup).not.toContain("undefined")
  })

  test("identifies an unlinked report without making an unsafe URL clickable", () => {
    const markup = renderToStaticMarkup(<SourceLinks sources={[{
      title: "Company annual results 2026", url: "javascript:alert(1)",
    }]} />)

    expect(markup).toContain("Company annual results 2026 · Link unavailable")
    expect(markup).not.toContain("<a ")
    expect(markup).not.toContain("javascript:")
  })
})
