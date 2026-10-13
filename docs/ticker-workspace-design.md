# Company research workspace

> Historical workspace design/audit record, superseded by the 13 October 2026 Quartr-based redesign. Use [DESIGN.md](../DESIGN.md) for current tokens, sizes, composition and mobile behavior, and [the implementation record](quartr-redesign-implementation.md) for current validation scope. Measurements and interactions below describe the earlier implementation.

Mode: Operate for source records; Read for research summary and history.

## Direction

Preserve StocksInHand's white canvas, charcoal text, cobalt controls and shared navigation. Quartr remains the style reference for restraint and evidence reading. The workspace uses real API data and no invented market content. See [functional contract](ticker-rebuild-contract.md) and [browser audit](ticker-ui-audit.md).

## Shared shell

Compact company identity, sector, latest-source date and quote precede one horizontal local navigation row. Open watchlist is a route link, not a save action. Quote freshness is distinct from the source date. The 1320px maximum workspace has 24px desktop and 16px mobile gutters. Errors and retries remain independent across brief, topics, discussion, records and history.

## Research summary

A real stored filing description is prominent when available. The exact backend setup fallback is treated as unavailable analysis; original material remains accessible through a compact disclosure. Existing topical evidence follows immediately. The six topics use native disclosures, with only the first available topic initially expanded. Full summaries are readable; model metadata and sources have separate disclosures. Filing details avoid repeating the header's price/change. Facts and interpretation, filing classification, themes and public-discussion coverage remain discoverable. Confidence describes a classification, not investment performance. Human-readable model names replace filesystem paths in the main interface.

## Source records

A search field and Filters & order disclosure precede the bounded chronological list and selected reader. Client filtering and ordering preserve record identity. On mobile, list and reader stack; Read selected record moves both focus and scroll to the article. A live status announces selection changes. Originals appear immediately below the record title; normalized equal URLs are deduplicated. Only meaningful saved context/change/research-angle text forms reading sections. Incomplete analysis is one concise notice. Source excerpts are optional disclosures, not repeated main text.

## Deep dive

A bounded chapter index accompanies the dated history on desktop. It collapses initially below 650px and can be expanded with a native control. Real details retain readable line breaks. Pending analysis is compact, with an original link. Repeated entry titles, excerpts and return links are removed. The service returns up to ten events; the UI does not claim a complete company history. Backend tone is not used as investment sentiment.

## Craft and validation

Page titles are 36px on desktop and 28px on mobile. Main prose is 16px, actionable metadata approximately 14px, and small secondary notes 12px. Standalone controls use 44px or larger hit areas. Text and URLs wrap, semantic classifications carry text labels, focus is visible and reduced motion is respected. Original links accept only HTTP(S).

The supported in-app browser now provides visual and interaction access. Desktop/mobile screenshots, search/empty/clear/filter/reader selection and mobile focus handoff were reviewed. Mobile source content moves earlier with no tested horizontal overflow. Frontend lint, 25 tests and the production static export pass. Detailed audit evidence lives in ticker-ui-audit.md. These checks do not constitute exhaustive accessibility or all-browser certification.
