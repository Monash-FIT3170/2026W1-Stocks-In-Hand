# Ticker UI audit and corrections

Scope: COH research summary, source records, and deep dive. Reference: the existing Quartr-inspired white/charcoal/cobalt design system. Reviewed the running app through the supported in-app browser at its desktop viewport and at 390px mobile width. Two isolated assessments covered visual UX and mechanical source checks. The initial detector reported no findings; browser inspection exposed issues it did not detect.

## Findings and fixes

| Priority | Observed problem | Correction |
| --- | --- | --- |
| P1 | Mobile header/navigation/tools buried the first source record around 745px | One compact local navigation row, consolidated company metadata and quotes, secondary filters in a disclosure. First record measured at 575px after fixes. |
| P1 | A pending record produced three large unavailable-analysis sections | One pending notice, immediate original-source action, meaningful saved fields only. |
| P1 | Database setup fallback was promoted as an AI-assisted company overview | Exact fallback detection; latest filing pending state is compact and expandable. Existing topical evidence leads. |
| P2 | Duplicate originals and repeated excerpts diluted history and record readers | Deduplicated normalized URLs; excerpts behind disclosures; history links no longer repeat entry prose. |
| P2 | 10–11px metadata and undersized controls reduced readability | Larger titles, 14px actionable metadata, 16px prose and expanded control hit areas. |
| P2 | Company and history rails competed with content | Company navigation moved above the work area. History index bounded on desktop and collapsed by default on mobile. |
| P2 | Mobile record selection had no explicit reader focus handoff | Named reader-jump button moves focus and scrolls to the selected article; selection announced by live status. |
| P2 | Raw model filesystem paths appeared as product data | Human-readable model name; original category identifier preserved as supplementary provenance. |

## Verification

Browser checks confirmed search empty state, clear filters, publisher filtering and updated selected reader. Mobile reader-jump focus passed. Mobile document width measured 375px inside the 390px viewport, with no horizontal overflow in the tested source view. Desktop and mobile screenshots were captured for all three views; existing routes, real database reads and authentication helpers are retained. No market claims, missing summaries or numeric metrics were invented.

The source service returns pending summaries for some real filings. Those are data availability limitations, now presented explicitly instead of inflated into empty reading sections. This audit does not claim exhaustive accessibility or every-browser certification.

Final visual review scored all six original UX findings resolved. The mobile history index starts closed; the first real entry was measured at 535px within the 844px-high viewport, with its original link visible. Frontend lint, 25 tests and the final production export passed. The browser viewport was restored after testing.
