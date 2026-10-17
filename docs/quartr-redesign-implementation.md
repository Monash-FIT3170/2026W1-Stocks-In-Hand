# Quartr-based redesign implementation

Implemented locally on 13 October 2026. The reference is Quartr's public pricing, API and hedge-fund pages; the study and measurements remain in `docs/design/quartr-study/`. Those captures are reference evidence, not application assets.

## Shared system

- Self-hosted official Inter Variable, including its OFL licence. Weight 550 provides consistent heading emphasis; body copy uses 400.
- A shared 1360px outer frame, desktop gutters of 32px and mobile gutters of 16px. Reading widths remain bounded within the wider composition.
- Near-black text, white reading surfaces, neutral stone evidence surfaces, cool control surfaces, restrained borders, and black primary buttons. Cobalt remains an interaction colour; financial sentiment retains semantic colours.
- Public navigation can become compact on scroll. Application navigation stays stable. Content is visible by default; the previous global reveal observer was removed.
- Shared focus, selection, caret, reduced-motion and icon-stroke rules. The root direction contract survives the production export.

## Surface changes

| Surface | Built composition |
|---|---|
| Home | Broad introduction and search beside a real latest-source exhibit; editorial feature rows below. Missing sources produce an honest workflow fallback. |
| Announcements | A horizontal filter strip, date-grouped document feed, and separate stone trending panel. Rankings and activity counts use returned data. Mobile controls occupy two columns. |
| Company summary | Prominent company identity, local underline navigation, white research document and separate evidence column tied to the selected topic. Mobile evidence follows the open topic. Pending filing analysis stays compact. |
| Source records | Search and filter tools above an index and full selected-record reader. Original-source action is prominent. Mobile defaults to the reader with explicit change-record/back controls. |
| Deep dive | Chronological research document with a separate contents rail; compact pending entries, legible substantive entries and original citations. Mobile contents collapse. |
| Search | Company ledger with distinct ticker, identity and sector roles. An entirely unavailable market-cap collection shows one explanatory note instead of a column of repeated N/A values. |
| Watchlist | Shared typography, neutral company grid and form/modal controls. Existing account gate and saving behaviour retained. |
| Sign-in / signup | A quiet split composition with introduction and task form; stacked on mobile. Other authentication pages inherit the same typography and controls. |
| Notification settings | Preferences form and separate status area, accurate confidence label and shared controls. |
| Result pages | Clear single-result panel for unsubscribe and notification verification, including missing-token branches. |
| About / data sources | Wide introductory composition, grouped workflow and source directory, clear heading/body contrast. |
| Terms / 404 | Bounded reading layout with contents navigation, or a single clear recovery task. |

The changes preserve API calls, source URLs, factual company records, authentication and alert-saving logic. Display labels now distinguish official filings, publisher news and public discussion. No database mutation was needed.

## Verification

- Production build passed, including all 60 static pages and its lint/type checks.
- Frontend tests: 30 passed across seven files. A new date-group test covers Sydney-local publication dates, UTC-midnight boundaries and missing dates.
- Static design detector ran once on changed UI targets and returned no findings.
- Browser captures compare desktop 1440 × 1000, mobile 390 × 844 and the original user viewport 1294 × 1143. JSON beside each capture records the measured viewport; that metadata is authoritative.
- Main company/feed captures use live returned data. The latest COH filing legitimately has pending analysis, while topical research contains stored substantive analysis.
- No horizontal overflow was found in the captured main-content layouts.
- A mobile source-index capture records the change-record interaction. No account creation, credential change, sign-out, preference save or token consumption was performed.

Final captures and the independent finish review are under `.impeccable/review/quartr-redesign/`. Documentation records the final built system in `DESIGN.md` and its sidecar.

The full independent review found the inspected design no longer significantly behind the public Quartr references in hierarchy, composition, type and surface craft. Its three mobile findings were corrected: full-strip date-popover positioning, an explicit accessible search name, and isolation of content covered by mobile navigation. The final verdict scored all three resolved and approved the reviewed scope. Open date controls were verified at 390px and 320px, including a selected range. Keyboard traversal stayed outside covered content; Escape restored focus to the toggle, and resizing to desktop cleared the navigation state.

## Limits

Rendered coverage includes the home, feed, all three COH research views, search, signup, information pages and unsubscribe's missing-token state. Authenticated watchlist and notification-settings layouts were changed and built, but their signed-in states have not been visually verified. Other authentication/result branches use the shared system and passed compilation, without state-by-state browser validation.

The comparison concerns hierarchy, type, spacing, grouping and horizontal balance. It does not claim pixel identity with Quartr, equivalence with its authenticated platform, or a measurable universal equality of aesthetic quality.
