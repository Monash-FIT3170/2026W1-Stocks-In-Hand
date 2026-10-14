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

### Analysis

**Artifact analysis**:
Analysing one artifact and recording the result: reading an announcement's document or the stored text, classifying an announcement, scoring its sentiment, summarising it, and recording all of it with its status. The analysis worker and the local loader both do it through one module.
_Avoid_: processing, enrichment, pipeline (for this step alone)

**Stored text**:
The text a news or public discussion collector saved with an artifact. It is analysed as it is, with no document to read.
_Avoid_: inline text, public discussion message (it covers news too)

**Category**:
The kind of company announcement an artifact is, such as a dividend announcement or half-year results, decided by fixed rules over its title, filename and text. An announcement the rules cannot place with confidence has no category.
_Avoid_: artifact type (the stored field), report type, classification (for the category itself)

**Prompt version**:
The version of the instructions an LLM summary was written from, recorded with each summary so summaries from older instructions can be found and regenerated.
_Avoid_: model version, template

**Sentiment bucket**:
One of the five themes a ticker's sentiment is broken down by: revenue, strategy, risk, dividend and organisational. A classified announcement counts in its category's one bucket, or in none (security notifications). Keywords place news and the announcements the rules could not classify.
_Avoid_: category (for a bucket), theme

**Artifact summary**:
What an artifact says in plain language: four text lines (summary, about, changed and matters) and, for an announcement, its claims sorted into confirmed facts and speculation. Each artifact has at most one, recorded with the model and prompt version that wrote it, and a new one replaces it whole.
_Avoid_: summary metadata, summary text (for the whole summary), AI summary

**Complete summary**:
An artifact summary with all four text lines, and both clarity lists when the artifact is an announcement. An artifact without one still needs summarising.
_Avoid_: current summary, full summary, summarised (for a partial summary)

**Summary request**:
A request on the analysis queue to write a new summary of one artifact from the text stored with it, leaving its sentiment and classification alone. The admin summary routes send one.
_Avoid_: resummarise job, summary job

**Artifact card**:
How one artifact appears in a feed: a tag, its title, who published it with a link to the original, and the about, changed and matters lines of its summary. A line the summary lacks is empty, never placeholder text or the artifact's raw text.
_Avoid_: announcement card (for both feeds), feed item formatter, news card

### Reading

**Read-model**:
A module that answers one page's question from stored data and writes nothing, such as the ticker brief or the watchlist summary (the brief also asks for a live quote). Its route only translates HTTP: parameters in, one read, a 404 for an unknown ticker, a declared response schema.
_Avoid_: view (for the module), query service, presenter

**Quote**:
A ticker's current price and previous close, read from Yahoo when a page asks and never stored in the database.
_Avoid_: market data, price data, ticker price

**Quote source**:
Where quotes come from: Yahoo in production, a fixed table in tests. It answers a quote or nothing, and the page then shows "N/A".
_Avoid_: quote client, price feed, Yahoo (for the interface)

**Ticker record**:
An artifact stored against a ticker, as the ticker's pages list it: newest published first, with its summary. The news feed shows the ten newest as artifact cards, and the deep dive shows them as research history.
_Avoid_: record (for any artifact), filing (for news), entry

**Ticker brief**:
What a ticker's research summary opens with: the company, its quote and latest signal, and the story, sources and clarity of its newest ticker record, beside that record's date and type and the kinds of record the ticker has had lately.
_Avoid_: overview (for the whole brief), aside (for the whole brief), summary (for the brief)

**Latest signal**:
The sentiment of a ticker's most recently published ASX announcement with a positive, neutral or negative label, shown on its brief and its watchlist card. News and public discussion never set it.
_Avoid_: latest sentiment, public sentiment, headline sentiment

**Category sentiment**:
A ticker's analysed sentiment in each sentiment bucket, plus public discussion, over the last year, read from what the analysis worker stored. Its groups are sentiment buckets, not categories, although the API names them `categories`.
_Avoid_: topic sentiment, category analysis, sentiment categories

**Watchlist summary**:
What an investor's watchlist page shows in one read: their oldest watchlist and, for each company in the order it was added, its latest signal and the brief line of its newest ticker record.
_Avoid_: watchlist details, watchlist page data

### People and access

**Investor**:
A person with an account who keeps watchlists and receives alerts.
_Avoid_: user, customer, subscriber

**Admin**:
An investor allowed to manage accounts and run jobs that cost money, such as scrapes and LLM summaries.
_Avoid_: superuser, operator

### Alerts

**Email sender**:
The one way the product sends email. It takes one email and answers accepted, recipient rejected, unavailable or misconfigured, and the caller decides what that outcome means for it. Brevo sends for real, the dry-run sender only logs, and a recording sender keeps each email for tests.
_Avoid_: mailer, provider (for the interface)

**Alert**:
An email telling an investor that an analysed artifact about a ticker on one of their watchlists matched their alert rule.
_Avoid_: notification (for the email; the notification message is the queue record an alert is made from)

**Rollup**:
The one email an investor gets for a scrape run instead of further alerts, once the run's per-investor cap is reached. It counts the matches the cap held back.
_Avoid_: digest (a Reddit digest is something else), summary email

**Alert delivery**:
Decides, for each investor watching a ticker, whether an analysed artifact becomes an alert, joins the scrape run's rollup or is held back. It sends what it decided through the email sender and records the outcome in the delivery ledger.
_Avoid_: notify (the Lambda that hands it SQS records), notification processing

**Delivery ledger**:
One row for each alert (per investor and artifact) and each rollup (per investor and scrape run). A row is claimed, and the claim committed, before its email is sent, so only one worker sends it at a time. The row then records sent, rejected, failed (a later claim may try again) or suppressed. Each outcome is also copied onto the investor's alert subscription, unless the subscription already shows a newer one.
_Avoid_: D17 fields or mirror (for the subscription's copy), delivery log

**Alert subscription**:
An investor's opt-in to email alerts at one address: whether alerts are on, where the address's verification stands, and the hash of the secret behind its unsubscribe links. Each investor has at most one, and changing the address starts verification again.
_Avoid_: notification preferences (for the stored record), subscriber

**Verification link**:
The signed, expiring link in a verification email that confirms an alert subscription's address. Only the newest request's link works, for 24 hours by default, and alerts go only to a verified address.
_Avoid_: confirmation token, magic link

### Running the system

**Runtime configuration**:
The settings a backend process runs with. Each is declared once with its default and limits. The whole set is read from the process's environment the first time any setting is used, and its secrets are read from SSM Parameter Store then. A value outside its limits fails that first read, naming the variable but never the value.
_Avoid_: env vars, config (for the whole set), settings file

**Secret**:
A setting AWS keeps in SSM Parameter Store, such as the database URL or the Brevo API key. A Lambda's environment holds only the parameter's name, in `<SETTING>_PARAMETER`, and the runtime configuration reads the value when it is built. A secret that may be missing reads as empty when its parameter does not exist, which switches its feature off. That is separate from a gated secret: the Marketaux token is gated but must exist, and the Reddit credentials may be missing although no switch gates them.
_Avoid_: credential, key (for every secret), SSM value

### Deploying

**Release**:
The three backend images built from one commit, named by its full Git SHA, deployed to the staging stack together with a value for every stack parameter. A rollback deploys an earlier release's images and keeps every other live value.
_Avoid_: deployment (for the versioned thing), build, version

**Release plan**:
The checked value of every stack parameter for one release, where each came from (set, live, default, derived or image), and the one `sam deploy` command that applies them. `python -m tools.release plan` writes it and `apply` runs it.
_Avoid_: parameter overrides, deploy config, change set (CloudFormation's preview of a deploy, which applying a plan creates)

**Gated secret**:
An SSM SecureString a Lambda reads only while a true/false stack parameter, its switch, is on, such as the Brevo API key behind NotificationsEnabled. A release plan checks that it exists whenever its switch is on.
_Avoid_: optional secret, feature secret

**Deploy roles**:
The two IAM roles a staging deploy runs as: the GitHub role a staging workflow job signs in as, and the CloudFormation execution role every change set is applied through.
_Avoid_: OIDC roles, CI role, deployment role (for both)
