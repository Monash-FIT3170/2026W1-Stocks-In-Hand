# Stocks In Hand

Stocks In Hand collects ASX company announcements, news and public discussion, analyses them, and turns them into plain-language briefs and alerts for retail investors.

## Language

### Companies and sources

**Ticker**:
An ASX company the product covers, identified by its stored symbol (upper-case, without the `.AX` suffix).
_Avoid_: stock, symbol (when the company is meant), company code

**Ticker catalogue**:
The single list of supported tickers and their facts: name, sector, industry, source adapter, announcements page and whether the weekly schedule includes it by default. Every other list of tickers is generated from it or checked against it.
_Avoid_: supported tickers list, default tickers, registry

**Source adapter**:
The per-company knowledge of how to list a company's recent announcements on its own website and fetch each one.
_Avoid_: scraper (for the whole concept), resolver

**Scheduled ticker**:
A ticker the weekly schedule scrapes when no override is configured.
_Avoid_: enabled ticker, default ticker

### Collecting

**Artifact**:
One item collected about the market: an announcement document, a news article or a public discussion post.
_Avoid_: item, record, document (for the whole concept)

**Scrape run**:
One request to collect a ticker's new announcements, or one target's public discussion, followed until it finishes as completed, partial or failed.
_Avoid_: job, crawl, collection (for announcements)

**Partial run**:
A scrape run that finished but could not collect some of its documents or posts.
_Avoid_: half-failed run

**Pipeline stage**:
One step an announcement passes through on its way to an analysis: discovery lists it, download stores it, analysis reads it.
_Avoid_: worker (for the step), queue

**Raw document**:
The stored, unchanging copy of an announcement document exactly as it was downloaded.
_Avoid_: file, object, PDF (for the concept)

**Public discussion**:
Posts about ASX companies on Reddit, Bluesky, Mastodon and finance blogs.
_Avoid_: social, forum posts, chatter

**Discussion source**:
A site public discussion is collected from, with its rules for what to collect and how to recognise a post it already has.
_Avoid_: platform (for the rules), scraper

**Target**:
What a discussion source collects from: a subreddit, a search query, a hashtag or a feed.
_Avoid_: query (for all four), channel

**Engagement**:
How much attention a public discussion post drew on its own site, such as its score or likes, comparable across discussion sources.
_Avoid_: popularity, score (for all sources)

**Ticker mention**:
A link between a public discussion post and a ticker it names, recording how the name was recognised.
_Avoid_: tag, match (for the stored link)

### People and access

**Investor**:
A person with an account who keeps watchlists and receives alerts.
_Avoid_: user, customer, subscriber

**Admin**:
An investor allowed to manage accounts and run jobs that cost money, such as scrapes and LLM summaries.
_Avoid_: superuser, operator
