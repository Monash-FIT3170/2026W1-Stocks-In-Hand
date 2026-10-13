# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

ASX-focused investors and research users who need to assess company updates quickly, then open the original evidence when an item merits investigation.

## Product Purpose

StonksInHand turns collected ASX filings, publisher coverage, and public-discussion records into a source-first research workspace. It helps users find the latest relevant company information, understand its context, and verify it against the underlying source.

## Positioning

The product combines multi-source ASX records with AI-assisted summaries, sentiment signals, and direct provenance links in a single research workflow rather than presenting unverified market commentary as fact.

## Operating Context

Users browse a market-wide update feed, narrow it by sector or date, open a company brief, and move between summary, source-record, and deep-dive views. They may save companies to a watchlist and configure alerts.

## Capabilities and Constraints

- Preserve existing API data, factual copy, routes, authentication behaviour, and error states unless a clarity change is required.
- Keep source URLs and citations prominent and distinguish official material from publisher and public-discussion records.
- The local build should run against the connected Supabase database; do not deploy without user approval.
- Do not invent financial metrics, company claims, testimonials, performance figures, or external affiliations.

## Brand Commitments

The product should remain recognisably StonksInHand: calm, exact, trustworthy, source-led, and task-oriented. Quartr is a reference for restraint, composition, navigation, and motion only; its trademarks, assets, wording, and proprietary imagery must not be copied.

## Evidence on Hand

- Supabase-backed ticker, artifact, summary, sentiment, and scrape-run data.
- Existing route content and source links in `frontend/src/app`.
- Product design system in `DESIGN.md`.

## Product Principles

- A source should be easier to inspect than a summary is to trust.
- Market relevance is conveyed by hierarchy and provenance, not decorative financial tropes.
- Dense research tasks need calm scanning paths and explicit states.
- Motion should explain continuity and interaction state, never obscure data.

## Accessibility & Inclusion

Meet WCAG AA, preserve complete keyboard access and reading order, provide clear focus states, and respect reduced-motion preferences.
