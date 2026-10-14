# Fresh ticker workspace: functional contract

The old ticker presentation is removed. Design around investor tasks and data, with no inherited composition. Style reference: https://quartr.com/ and publicly visible product imagery. Borrow restraint, clear evidence reading, typography and purposeful interactions, without copying Quartr assets/claims. Preserve StocksInHand app-wide nav, palette and fonts. Do not inspect Git history, old ticker screenshots, UI_AUDIT.md or ticker sections in DESIGN.md.

## Scope

Rebuild all three direct routes `/ticker/[symbol]/`, `/ticker/[symbol]/news/`, `/ticker/[symbol]/deep-dive/`. Preserve static params/metadata and auth. COH is acceptance case, BHP provides populated data. No invented data, charts, transcripts, backend changes or mutation requests. No old hero/horizontal-tab/card/sidebar composition. Other pages must remain unaffected.

## Reusable inputs

Read components/layout/AppFrame.jsx and AppFrame.module.css for nav/tokens/fonts, components/ui and other reusable non-ticker controls. lib/api.js owns auth/URL encoding/caching. components/sources/CitationLinks.jsx is shared with announcements and was relocated intact; reuse is optional, its arrangement imposes no constraint. components/company/CompanyData.jsx is a presentation-free provider; useCompanyData() returns `{symbol,overview,aside,isLoading,error,retry}`. useCompanyResource(fetcher,symbol,enabled) returns `{data,isLoading,error,retry}`; resources fail/retry independently. You can refine these company helpers. Read PRODUCT.md. Avoid old design prose.

## API reads

Frontend /api proxies to localhost:8000. Both servers and Supabase are running. Use existing fetch helpers only. The authoritative backend contracts are the response schemas in backend/app/schemas: ticker_brief.py, ticker_records.py, category_sentiment.py and public_discussion.py. A migrated database already holds every supported ticker. 404, empty arrays, nulls and request failures need independent honest handling. Do not run POST scrape/generate routes.

### Brief: fetchTickerBrief(symbol)

GET /tickers/symbol/{symbol}/brief -> `{overview,aside}`.

overview = `{symbol,company_name,sector,current_price,day_change,last_updated,story,sources_count,sources,clarity,sentiment_status,sentiment_label,latest_signal_confidence_pct,latest_signal_model,latest_signal_analyzed_at}`. Price/day change are formatted strings, N/A when quote fails. last_updated is source display date, not quote time. story is the latest record's stored summary (its about line, else its summary line), or null when that record has no summary. sources_count counts this brief's links, not all records. Sentiment label = Generally Positive/Generally Negative/Neutral/Unavailable; status = available/unavailable. They and the latest_signal fields describe the latest published ASX announcement with stored sentiment; news and public discussion never set them. Confidence is formatted percentage or N/A and describes the latest filing model classification, NOT public sentiment, return probability or investment advice. Model and analysis ISO timestamp may be null.

clarity = `{is_classified:boolean,confirmed_facts:string[],speculation:string[]}`. Keep factual claims distinct from interpretation; explicit unclassified state and AI-assisted attribution. Never infer facts/interpretations from prose when arrays are missing.

aside = `{key_numbers:{label,value}[],themes:string[]}`. Key numbers are the latest filing's date and type; price and day change are in the overview only. Themes are filing category activity, not financial conclusions.

Source = `{label,title,url,published_at:ISO|null,evidence_text:string|null}`. Keep original links meaningful, validate HTTP(S) URLs and dates, external rel noreferrer/noopener. Missing source links remain visibly missing.

### Records: fetchTickerNews(symbol)

GET /tickers/symbol/{symbol}/news-feed -> Record[] (up to ten persisted records, newest first; not exhaustive, no server pagination).

Record = `{id,ticker,tag,time,title,about,changed,matters,url,source_type,source_name,source_label,sources:Source[]}`. id is the record's stable artifact id. time is DISPLAY date; no ISO date is supplied. Preserve context, change, research angle, provenance and original-source link. Distinguish official filings, publisher news, public discussion. about, changed and matters are null until the record's summary has that line; never put raw text or invented summaries in their place. source_name is ASX for filings, the platform for Reddit posts, else the publisher or provider, or null. Client-side search/filter/reader selection welcome; start fresh rather than copying announcement-card composition.

### History: fetchTickerDeepDive(symbol)

GET /tickers/symbol/{symbol}/deep-dive-timeline -> Event[] (up to ten persisted events, newest first).

Event = `{tag,title,date,detail,sources:Source[]}`. date is a DISPLAY date. detail is the persisted summary text, or null when the record has no summary. Chronology, long readable detail, source provenance and links remain accessible. Do not claim an entire company history or generated cross-record conclusions.

### Categories: fetchTickerCategorySentiment(symbol)

GET /sentiment/{symbol} -> `{ticker,status,model_used,latest_analyzed_at,categories}`. status = available/partial/unavailable. categories keys = revenue,strategy,risk,dividend,organisational,user_discussion. A classified announcement counts in its category's one bucket, or in none (security notifications); news and unclassified announcements are placed by keyword, possibly in several buckets; public discussion counts only in user_discussion.

Each result = `{summary,available,sentiment_label,label,score,confidence_score,agreement_score,distribution,model_used,chunks_used,chunks_analyzed,sources_count,sources,latest_analyzed_at}`. Numbers nullable; confidence_score is 0..1, ZERO is valid, null is missing. Full summaries must be readable/expandable, with truthful missing evidence, sentiment text and category citations. Category sources = PublicSource[] `{source_type,title?,url?,author?,published_at?}`. Never attach overview citations to another category as evidence.

### Discussion: fetchTickerPublicDiscussionStatus(symbol)

GET /public-discussion/ticker/{symbol}/status -> `{ticker,status,counts,sources,latest_collected_at}`. counts = `{total,pending,queued,analyzing,completed,failed}`; sources = name/count map. status commonly available/partial/pending/failed/unavailable. Preserve coverage/freshness somewhere discoverable, with public discussion distinct from official sources. Avoid making infrastructure counters the dominant investor content.

## Must remain discoverable

Company identity and quote availability, latest stored research, sources and AI attribution, factual clarity vs interpretation, six topical analyses with coverage/model confidence, key numbers and themes, discussion collection/analysis status, record contexts/changes/research angles, historic detail/dates/originals. Their hierarchy and interaction are yours to invent. Avoid giant empty grids for absent data; useful disclosure beats uniform panels. No new features needing unsupported APIs. Keyboard accessibility, visible focus, mobile/desktop layouts, long strings, reduced motion, independent loading/error/empty/retry states.

## Validation

Frontend lint/tests/static production build, API reads for COH/BHP, no backend writes. Browser CUA previously policy-blocked this local URL: do not circumvent via alternate surfaces, Playwright or CDP. Public Quartr access may be inspected where allowed. Disclose missing local screenshot evidence. Parent independently reviews integration and contracts.
