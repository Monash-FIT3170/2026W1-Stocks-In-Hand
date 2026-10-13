# Announcements source records: scoped audit

Scope: only Latest source records and its record component. The announcements hero, market-status panel, trending companies, sector/date filters, navigation and pagination logic are preserved.

## Corrections

| Finding | Change |
| --- | --- |
| Large cards dominated by unavailable analysis | Compact editorial rows; one pending status; substantive context inline and extra research in a native disclosure. |
| Narrow headline column forced excessive wrapping | Full-width natural wrapping, 23px desktop and 20px mobile headings. |
| Ticker/type/publisher/date split between numbered rail and card | One wrapping metadata line, without decorative numbering or permanent blue card accents. |
| Originals and company actions buried beneath empty sections | Immediate original/company links with 44px hit areas. |
| Generic market items linked to unsupported ASX company page | Market-wide label; company actions only for supported ticker routes. |
| Duplicate or unsafe original URLs | HTTP(S) validation and normalized URL deduplication. |
| Repeated headline used as context | Exact duplicate text suppressed; real supplied analysis preserved. |

The initial layout detector found no issues; independent browser/design and mechanical assessments identified the defects above. The final visual review marked all five scoped UX findings resolved. Desktop and 390px mobile screenshots show surrounding sections preserved. The first desktop record measured about 195px, compared with roughly 285px before. The mobile document was 375px wide within the 390px viewport.

Lint and 29 frontend tests passed. Browser pagination loaded twelve records, and no unsupported ASX company links remained. Source descriptions and summaries remain database-backed; absent analysis is not fabricated. Production export validation is recorded in the task response.
