import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, test } from "vitest"

import { ClarityLayer } from "./ClarityLayer"

describe("ClarityLayer claim traceability", () => {
  test("renders an exact passage and dated source without changing the claim text", () => {
    const markup = renderToStaticMarkup(
      <ClarityLayer
        clarity={{
          is_classified: true,
          confirmed_facts: ["Revenue increased by 12%."],
          speculation: [],
          traceable_claims: [
            {
              text: "Revenue increased by 12%.",
              kind: "confirmed_fact",
              source: {
                evidence_text: "Revenue increased by 12%.",
                label: "ASX Announcement",
                published_at: "2040-02-03T00:00:00+00:00",
                title: "Results update",
                url: "https://example.test/results.pdf",
              },
            },
          ],
        }}
      />,
    )

    expect(markup).toContain("Revenue increased by 12%.")
    expect(markup).toContain("Exact passage")
    expect(markup).toContain("03 Feb 2040")
    expect(markup).toContain('href="https://example.test/results.pdf"')
    expect(markup).toContain('rel="noopener noreferrer"')
  })

  test("keeps the existing shared citation layout for an older API response", () => {
    const markup = renderToStaticMarkup(
      <ClarityLayer
        clarity={{
          is_classified: true,
          confirmed_facts: ["A legacy claim."],
          speculation: [],
        }}
        sources={[
          {
            label: "ASX Announcement",
            title: "Legacy update",
            url: "https://example.test/legacy.pdf",
          },
        ]}
      />,
    )

    expect(markup).toContain("Sources")
    expect(markup).not.toContain("Source unavailable")
  })
})
