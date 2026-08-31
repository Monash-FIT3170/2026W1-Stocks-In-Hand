# 2026W1-Stocks-In-Hand

## People

* Arv Surana
* Mahissh Pranav Surendhar Rajasudha
* Christian Rogan
* Merrick Campbell
* Akshara Balreddygari
* Akshat Porwal
* Mitchell Padula
* James Baxter
* Raveen Munasinghe
* Roshan Raj Saravanan
* Moin Vohra
* Caden Arnold
* Jordan Tran
* Alan Sebastian
* Aadi Kapoor


# Project

A full-stack proof of concept for financial sentiment analysis on ASX/stock news.

**Stack:** Next.js → FastAPI → Playwright → FinBERT → PostgreSQL, containerised with Docker Compose.

---

## What it does

- Paste any financial headline → FinBERT classifies it as **positive**, **negative**, or **neutral**
- Scrape live headlines from Yahoo Finance via Playwright
- Scraped announcements, Reddit, Bluesky and Mastodon posts, and their summaries/sentiment persisted to PostgreSQL
- Send optional Brevo email alerts when watched tickers match an investor's sentiment rule

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- No Python, Node, or npm needed locally

---

## Running the project

In the root folder of the project
```bash
docker compose -f docker-compose.yml up --build
```

Then open:
| URL | What |
|---|---|
| http://localhost:3000 | Frontend UI |
| http://localhost:8000/docs | FastAPI auto-generated API docs |
| http://localhost:8000/headlines | Raw scraped headlines (JSON) |

First boot takes a few minutes — FinBERT (~500MB) and Playwright downloads on first run and is cached after that.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `REDDIT_CLIENT_ID` | For Reddit | Client ID from a Reddit script application. |
| `REDDIT_CLIENT_SECRET` | For Reddit | Client secret from the same Reddit application. |
| `BLUESKY_IDENTIFIER` | No | Bluesky handle for authenticated search. Leave empty for public search. |
| `BLUESKY_APP_PASSWORD` | No | Bluesky app password. Must be set with `BLUESKY_IDENTIFIER`. |
| `PUBLIC_DISCUSSION_FEED_URLS` | For blogs | Comma-separated HTTPS RSS or Atom feed allowlist. |
| `SCHEDULED_PUBLIC_DISCUSSION_SOURCES` | No | Scheduled subset. Defaults to `bluesky,mastodon`. |
| `PUBLIC_DISCUSSION_PER_SOURCE_LIMIT` | No | Scheduled item limit per source. Defaults to `10` and is capped at `25`. |
| `PUBLIC_DISCUSSION_SEARCH_QUERY` | No | Shared Reddit, Bluesky, and Mastodon search value. Defaults to `ASX`. |
| `LLM_PROVIDER` | No | Defaults to `bedrock`. `groq` remains available only for an explicit local rollback. |
| `BEDROCK_ENABLED` | For generated summaries | Must be `true` before the app invokes Bedrock. Defaults to `false`. |
| `BEDROCK_MODEL_ID` | No | Defaults to regional `openai.gpt-oss-120b-1:0`. |
| `BEDROCK_SERVICE_TIER` | No | `default`, `flex`, or `priority`. AWS queued analysis uses `flex`. |
| `BEDROCK_MAX_PROMPT_CHARS` | No | Rejects prompts over 30,000 characters by default. |
| `BEDROCK_MAX_OUTPUT_TOKENS` | No | Caps generated output at 1,024 tokens by default. |
| `GROQ_API_KEY` | Local rollback only | Not loaded by the AWS deployment. |
| `GROQ_MODEL` | Local rollback only | Defaults to `openai/gpt-oss-120b`. |
| `FINBERT_MODEL` | No | Defaults to `/app/finbert` (bundled in Docker image) |
| `NOTIFICATIONS_ENABLED` | No | Master switch for watchlist alerts. Defaults to `false` outside the development compose stack. |
| `NOTIFICATIONS_DRY_RUN` | No | Renders and logs alerts without contacting Brevo. The example environment sets it to `true`. |
| `ALERT_SENDER_EMAIL` | Live Brevo only | Sender address verified in the Brevo account. |
| `ALERT_SENDER_NAME` | No | Display name for alert emails. Defaults to `Stocks in Hand`. |
| `BREVO_API_KEY` | Live Brevo only | Brevo API key. Store it outside source control. |
| `BREVO_API_KEY_PARAMETER` | AWS only | SSM parameter name containing the Brevo API key. |
| `BREVO_API_BASE_URL` | No | Defaults to `https://api.brevo.com/v3`. |
| `ALERT_DAILY_BUDGET` | No | Maximum alert delivery commitments across the last 24 hours. Defaults to `180`. |
| `ALERT_MAX_PER_INVESTOR_PER_RUN` | No | Direct alerts per investor and scrape run before one rollup. Defaults to `5`. |
| `ALERT_DEFAULT_MIN_CONFIDENCE` | No | Default rule threshold from `0` to `1`. Defaults to `0.75`. |
| `ALERT_CLAIM_STALE_MINUTES` | No | Age at which an unfinished delivery claim may be retried. Defaults to `15`. |
| `FRONTEND_BASE_URL` | No | Public frontend base used in unsubscribe links. Defaults to `http://localhost:3000`. |
| `ALERT_VERIFICATION_TOKEN_TTL_HOURS` | No | Lifetime of email confirmation links. Defaults to `24`. |

### Use Bedrock locally

Set `BEDROCK_ENABLED=true` and add temporary AWS credentials to `backend/.env`.
Use an IAM identity limited to `bedrock:InvokeModel` for the approved model. Do
not use an AWS root key. Then let Compose use that file for interpolation:

```bash
docker compose --env-file backend/.env -f docker-compose-dev.yml up -d --build backend
```

The normal Compose command keeps placeholder AWS credentials, so it cannot make
an accidental paid Bedrock call. Confirm model access before testing one bounded
summary request.

## Watchlist email alerts

Use the development compose file when working on alerts:

```bash
docker compose -f docker-compose-dev.yml up --build
```

This stack starts PostgreSQL and the app. Sign in, then open
`http://localhost:3000/settings/notifications` to choose sentiment labels and
a confidence threshold.

The development stack uses `NOTIFICATIONS_DRY_RUN=true` by default. It renders
both email formats and records a stable dry-run message ID. It does not contact
Brevo. For a real local send, set `NOTIFICATIONS_DRY_RUN=false`,
`BREVO_API_KEY`, a Brevo-verified `ALERT_SENDER_EMAIL`, and an HTTPS
`FRONTEND_BASE_URL` in the root `.env`.

Production delivery requires HTTPS confirmation and unsubscribe links. The
sender must be verified in Brevo. Alert recipients confirm through the app's
signed email link, so they do not need to be added to Brevo first. See the
[deployment guide](deployment.md) for staged enable and rollback steps.

## API endpoints

### Core
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/docs` | FastAPI auto-generated interactive API docs |
| GET | `/tickers` | List all implemented ASX tickers |

### Sentiment (FinBERT)
| Method | Path | Description |
|---|---|---|
| POST | `/analyse` | Run FinBERT on raw text. Body: `{ "text": "..." }`. Returns label (positive/negative/neutral), confidence score, and full distribution |
| POST | `/sentiment/{ticker}` | Admin-only full pipeline: pulls recent ASX artifacts plus relevant Reddit, Bluesky and Mastodon posts, runs Bedrock categorisation and summarisation, then FinBERT on each category. Returns per-category sentiment breakdown and stores an aggregate sentiment for the latest ticker artifact. Params include `reddit_limit`, `bluesky_limit` and `mastodon_limit` |

### Reddit (PRAW)
| Method | Path | Description |
|---|---|---|
| POST | `/reddit/scrape` | Admin-only bounded Reddit collection. Params: `subreddit` (default: ASX), `limit` (default: 10) |
| GET | `/reddit/ticker-sentiment/{ticker_symbol}` | Authenticated Bedrock summary of stored Reddit posts mentioning a ticker. Returns dominant sentiment and key themes. Params: `days` (default: 30), `limit` (default: 50) |

### Bluesky (public API)
| Method | Path | Description |
|---|---|---|
| POST | `/bluesky/scrape` | Admin-only public or authenticated Bluesky collection. Params: `query` (default: ASX), `limit` (default: 25) |

### Mastodon (public API)
| Method | Path | Description |
|---|---|---|
| POST | `/mastodon/scrape` | Admin-only `aus.social` hashtag collection. Params: `tag` (default: ASX), `limit` (default: 25) |

### Blogs and public discussion status

| Method | Path | Description |
|---|---|---|
| POST | `/blogs/scrape` | Admin-only RSS or Atom collection. `feed_url` must be in `PUBLIC_DISCUSSION_FEED_URLS` |
| GET | `/public-discussion/ticker/{ticker}/status` | Return collection and analysis counts for one ticker |
| POST | `/public-discussion/analysis/requeue` | Admin-only recovery endpoint. Defaults to a dry run. Set `execute=true` to queue a bounded batch |

### Bedrock analysis routes
| Method | Path | Description |
|---|---|---|
| POST | `/gemini/categorise/recent` | Admin-only legacy route name. Uses Bedrock on recent ASX artifacts and classifies them into financial categories. Params: `ticker`, `days`, `limit`, `offset`, `batch_size` |

### Scraping
| Method | Path | Description |
|---|---|---|
| POST | `/scrape/{ticker}` | Trigger a background ASX announcement scrape for any supported ticker. Automatic schedules remain separately controlled by `SCHEDULED_TICKERS`. |
| GET | `/headlines` | Scrape live Yahoo Finance headlines via Playwright (default ticker BHP.AX) |

### Storage (direct DB access)
| Method | Path | Description |
|---|---|---|
| POST | `/artifact-sentiments/` | Manually store a sentiment record against an artifact |
| GET | `/artifact-sentiments/artifact/{artifact_id}` | Get all sentiment records for an artifact |
| GET | `/artifact-sentiments/{sentiment_id}` | Get a single sentiment record |

### Watchlist notifications

| Method | Path | Description |
|---|---|---|
| GET | `/notifications/preferences` | Read the signed-in investor's rule, verification state, and latest delivery status |
| PUT | `/notifications/preferences` | Enable or disable alerts and update sentiment labels and confidence threshold |
| POST | `/notifications/preferences/resend-verification` | Resend the Brevo confirmation email, limited to once per minute |
| POST | `/notifications/verify` | Confirm an alert email address with a signed, expiring token |
| POST | `/notifications/unsubscribe` | Disable a matching subscription with a public token; valid and invalid tokens return the same response |
---

## Stopping
```bash
docker compose down        # stop containers
docker compose down -v     # stop + wipe the database
```

## Automatic local announcement bootstrap

`docker-compose-dev.yml` includes a one-shot `content-bootstrap` service. After
the backend is healthy it checks the official company sources for the supported
tickers, processes at most three announcements per ticker from the last year,
and exits. Existing documents and complete summaries are retained, so the job
is safe to run again on later Docker starts.

Local Docker uses the Groq fallback by default. Add `GROQ_API_KEY` to the
untracked `backend/.env` to generate structured summaries. Without a key, the
website still starts and collected announcements remain available, but summary
generation is skipped. The bootstrap is development-only and is not used by
the AWS deployment.

To start the application without running collection, name only the long-running
services:

```bash
docker compose -f docker-compose-dev.yml up --build db backend frontend
```

## Setup
Before doing any development work in this repository, you must run the init.sh script. It only needs to be run once, unless dependencies change majorly and it may need to be re-run, but this will be clearly communicated

In the root of the repository run the following:
```bash
./init.sh
```

### On macOS and Linux
If you're on macOS or Linux, you may need to change the file permissions first

In the root of the repository run the following:
```bash
chmod +x ./init.sh
./init.sh
```

## Running the tests
In the root folder of the project
```bash
docker compose -f docker-compose-tests.yml up --build
```

## Document classification

ASX documents use the deterministic, in-process `rules-v2` classifier. It
returns `classified`, `needs_review` or `unknown`, together with stable category
identifiers, ordered candidates and matched rule evidence. Its numeric score is
a rules score, not a probability. Ambiguous and unknown results remain
`UNKNOWN` for legacy consumers.

See [the advanced content classification guide](docs/advanced-content-classification.md)
for the taxonomy, fixture evaluator, extension process and bounded
reclassification command.
