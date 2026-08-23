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
- Scraped announcements, Reddit posts, and their summaries/sentiment persisted to PostgreSQL

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
| `REDDIT_CLIENT_ID` | Yes | From reddit.com/prefs/apps — the string under "personal use script", key for developers available on Discord. |
| `REDDIT_CLIENT_SECRET` | Yes | The secret field from your Reddit app, key for developers available on Discord. |
| `REDDIT_SEED_SUBREDDIT` | No | Subreddit scraped on backend startup. Defaults to `ASX` |
| `REDDIT_SEED_LIMIT` | No | Number of Reddit posts fetched on backend startup. Defaults to `50` |
| `GROQ_API_KEY` | Yes | From console.groq.com — used for ticker categorisation and Reddit summarisation |
| `GROQ_MODEL` | No | Defaults to `openai/gpt-oss-120b` |
| `GEMINI_API_KEY` | No | Legacy setting; ticker sentiment does not use Gemini |
| `GEMINI_MODEL` | No | Legacy Gemini model setting |
| `FINBERT_MODEL` | No | Defaults to `/app/finbert` (bundled in Docker image) |


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
| POST | `/sentiment/{ticker}` | Full pipeline: pulls recent ASX artifacts + Reddit posts for a ticker, runs Groq categorisation/summarisation, then FinBERT on each category. Returns per-category sentiment breakdown and stores an aggregate sentiment for the latest ticker artifact |

### Reddit (PRAW)
| Method | Path | Description |
|---|---|---|
| POST | `/reddit/scrape` | Queue a background Reddit scrape and store posts as artifacts. Params: `subreddit` (default: ASX), `limit` (default: 10) |
| GET | `/reddit/ticker-sentiment/{ticker_symbol}` | Read stored Reddit posts mentioning a ticker, summarise with Groq/LLaMA, return dominant sentiment and key themes. Params: `days` (default: 30), `limit` (default: 50) |

### Groq / legacy LLM route
| Method | Path | Description |
|---|---|---|
| POST | `/gemini/categorise/recent` | Legacy route name. Uses Groq on recent ASX artifacts for a ticker and classifies them into financial categories (earnings, dividends, etc). Params: `ticker`, `days`, `limit`, `offset`, `batch_size` |

### Scraping
| Method | Path | Description |
|---|---|---|
| POST | `/scrape/{ticker}` | Trigger background ASX announcement scrape for a ticker. Available tickers: BHP, CBA, ANZ, CSL, WES |
| GET | `/headlines` | Scrape live Yahoo Finance headlines via Playwright (default ticker BHP.AX) |

### Storage (direct DB access)
| Method | Path | Description |
|---|---|---|
| POST | `/artifact-sentiments/` | Manually store a sentiment record against an artifact |
| GET | `/artifact-sentiments/artifact/{artifact_id}` | Get all sentiment records for an artifact |
| GET | `/artifact-sentiments/{sentiment_id}` | Get a single sentiment record |
---

## Stopping
```bash
docker compose down        # stop containers
docker compose down -v     # stop + wipe the database
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
