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
- Some results persisted to PostgreSQL

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
| http://localhost:8000/results | Last 10 sentiment results (JSON) |

First boot takes a few minutes — FinBERT (~500MB) and Playwright downloads on first run and is cached after that.


## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/analyse` | Run FinBERT on `{ "text": "..." }` |
| POST | `/sentiment/{ticker}` | Run FinBERT on ASX/Gemini categories and Reddit/Groq `user_discussion` for a ticker |
| GET | `/results` | Last 10 saved results |
| GET | `/headlines` | Scrape Yahoo Finance headlines |

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
