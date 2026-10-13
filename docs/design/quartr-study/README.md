# Reference study evidence

Captured 13 October 2026 in the Codex in-app browser. These are inspection artifacts for the [shared design plan](../../quartr-design-plan.md) and [page-by-page plan](../../quartr-page-by-page-plan.md).

## Method

Quartr's three user-supplied public pages were inspected through rendered screenshots and read-only DOM/computed-style measurements. Current StonksInHand pages were inspected through rendered screenshots and route/component source. No authenticated Quartr flows were visited.

Each JSON file records the actual browser viewport and measured element properties. The viewport data is authoritative; filenames alone are not a responsive verification result. Initial animation/loading captures were replaced where a stable view was available. The watchlist screenshot remains explicitly an initial unauthenticated/loading view.

Reference captures here are desktop at 1280 × 720. Current-app captures include desktop at 1280 × 720 and mobile at 390 × 844. Quartr mobile measurements were not confirmed in this pass, so no unverified mobile reference files are included. Mobile dimensions recommended in the plan are proposed app values, not claimed Quartr measurements.

## Quartr public references

| Reference | Evidence |
|---|---|
| [Pricing](https://quartr.com/pricing) | [Opening screenshot](quartr-pricing-desktop.png), [comparison section](quartr-pricing-matrix.png), [measurements](quartr-pricing-desktop.json) |
| [Quartr API](https://quartr.com/products/quartr-api) | [Opening screenshot](quartr-api-desktop.png), [overview and facts](quartr-api-overview.png), [dataset grouping](quartr-api-datasets.png), [measurements](quartr-api-desktop.json) |
| [Hedge funds](https://quartr.com/use-cases/hedge-funds) | [Opening screenshot](quartr-hedge-desktop.png), [feature grouping](quartr-hedge-features.png), [measurements](quartr-hedge-desktop.json) |

## Current application evidence

| Surface | Evidence |
|---|---|
| Home desktop | [Screenshot](app-home-desktop.png), [measurements](app-home-desktop.json) |
| Announcements desktop | [Screenshot](app-announcements-desktop.png), [measurements](app-announcements-desktop.json) |
| COH summary desktop | [Screenshot](app-ticker-summary-desktop.png), [measurements](app-ticker-summary-desktop.json) |
| COH source library mobile | [Screenshot](app-ticker-sources-mobile.png), [measurements](app-ticker-sources-mobile.json) |
| COH history mobile | [Screenshot](app-ticker-history-mobile.png), [measurements](app-ticker-history-mobile.json) |
| Search mobile | [Screenshot](app-search-mobile.png), [measurements](app-search-mobile.json) |
| Watchlist initial unauthenticated/loading | [Screenshot](app-watchlist-gated.png), [measurements](app-watchlist-gated.json) |
| Sign-in mobile | [Screenshot](app-sign-in.png), [measurements](app-sign-in.json) |
| Signup mobile | [Screenshot](app-sign-up.png), [measurements](app-sign-up.json) |
| About mobile | [Screenshot](app-about.png), [measurements](app-about.json) |
| Data sources mobile | [Screenshot](app-data-sources.png), [measurements](app-data-sources.json) |
| Terms mobile | [Screenshot](app-terms.png), [measurements](app-terms.json) |
| Unsubscribe missing-token mobile | [Screenshot](app-unsubscribe-missing-token.png), [measurements](app-unsubscribe-missing-token.json) |

## Interpretation and limits

[Proposed colour contrast calculations](proposed-contrast-check.json) cover the new metadata, functional boundary, neutral-surface warning and retained cobalt colours against four proposed light surfaces.

- A computed font-family declaration describes requested font selection. Final implementation verification must also confirm the actual loaded Inter face and successful font requests.
- Captures describe one viewport/data state. They do not establish complete responsive, accessibility or authenticated-flow validation.
- Current company/feed records were database-backed. The plan distinguishes genuine missing/pending data from visual shortcomings.
- Source-only route states are marked in the page inventory. No actual sign-out, account creation, credential change, alert preference save or token consumption was performed for this design study.
- Screenshots preserve the inspected reference for comparison; they are not assets proposed for inclusion in StonksInHand.
