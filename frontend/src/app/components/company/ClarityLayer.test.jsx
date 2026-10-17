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
                evidence_text: "Revenue totalled $112 million, up from $100 million last year.",
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
    expect(markup).toContain("Revenue totalled $112 million, up from $100 million last year.")
    expect(markup).toContain("Exact passage")
    expect(markup).toContain("3 Feb 2040")
    expect(markup).toContain('href="https://example.test/results.pdf"')
    expect(markup).toContain('rel="noopener noreferrer"')
  })

  test("shows missing passages and missing sources without inventing evidence", () => {
    const markup = renderToStaticMarkup(
      <ClarityLayer
        clarity={{
          is_classified: true,
          confirmed_facts: ["A paraphrased claim."],
          speculation: ["Growth may continue."],
          traceable_claims: [
            {
              text: "A paraphrased claim.",
              kind: "confirmed_fact",
              source: { url: "https://example.test/results.pdf" },
            },
            { text: "Growth may continue.", kind: "speculation", source: null },
          ],
        }}
      />,
    )
    expect(markup).toContain("Exact passage unavailable")
    expect(markup).toContain("Date unavailable")
    expect(markup).toContain("Source unavailable")
    expect(markup).not.toContain("<blockquote")
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

    expect(markup).toContain('href="https://example.test/legacy.pdf"')
    expect(markup).not.toContain("Source unavailable")
  })

  test("rejects unsafe claim links without exposing them as citations", () => {
    const markup = renderToStaticMarkup(
      <ClarityLayer clarity={{
        is_classified: true, confirmed_facts: ["A claim."], speculation: [],
        traceable_claims: [{ text: "A claim.", kind: "confirmed_fact", source: {
          url: "javascript:alert(1)", evidence_text: "A claim.",
        } }],
      }} />,
    )
    expect(markup).toContain("Source unavailable")
    expect(markup).not.toContain("javascript:")
    expect(markup).not.toContain("<blockquote")
  })

})
