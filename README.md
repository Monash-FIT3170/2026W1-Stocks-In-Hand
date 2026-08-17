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

`docker-compose.yml` loads secrets from `backend/.env`, which is gitignored
and not created automatically by `init.sh` — create it once before your
first run:

```bash
cp backend/.env.example backend/.env
```

Then, fill in `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` (see "Environment
variables" below) and, in the root folder of the project:
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

### Previewing the static frontend export

`docker compose up` runs the frontend in `next dev` mode, which does not catch
everything that breaks under the static export (`next build` with
`output: "export"`) actually deployed to CloudFront in staging/production.
Before relying on a frontend change surviving deployment, preview the real
static build:

```bash
cd frontend
npm run preview   # next build && npx serve out
```

This builds `frontend/out` exactly as CI does and serves it statically, so
anything that only works under a live Next.js server (and not a static
export) shows up locally instead of only after a deploy.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `REDDIT_CLIENT_ID` | Yes | From reddit.com/prefs/apps — the string under "personal use script", key for developers available on Discord. |
| `REDDIT_CLIENT_SECRET` | Yes | The secret field from your Reddit app, key for developers available on Discord. |
| `REDDIT_SEED_SUBREDDIT` | No | Subreddit scraped on backend startup. Defaults to `ASX` |
| `REDDIT_SEED_LIMIT` | No | Number of Reddit posts fetched on backend startup. Defaults to `50` |
| `GROQ_API_KEY` | Yes | From console.groq.com — used for ticker categorisation and Reddit summarisation via meta/LLaMA |
| `GROQ_MODEL` | No | Defaults to `llama-3.3-70b-versatile` |
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

## Local backend development without Docker

Docker is the supported way to run this project, but if you want a local
debugger/faster edit loop for backend code, the pinned Python version is
`3.11` (see `backend/.python-version`, matching the API/scraper Lambda images
and `backend/Dockerfile`'s base image).

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
```

`requirements-dev.txt` installs the same pinned versions as the split Lambda
requirement files (`requirements-api.txt`, `requirements-analysis.txt`,
`requirements-scraper.txt`, `requirements-runtime.txt`), plus the two
local-only extras (`uvicorn`, `alembic`) needed to run a dev server and
migrations outside the pipeline. This intentionally keeps local dev on the
same dependency versions that actually ship to Lambda — see
`recommendations.md` for why that used to drift. Add
`requirements-testing.txt` on top if you also want `pytest`/`pylint`/`mypy`/
`bandit` locally.

You'll also need Playwright's browser binaries (`playwright install
chromium`) and a running Postgres instance — `DATABASE_URL` in `backend/.env`
should point at it. See `backend/.env.example` for every variable the backend
reads, including which ones are optional/Lambda-only.

### Running the pipeline locally (discovery -> download -> analysis)

By default, `POST /scrape/{ticker}` is disabled locally (`DISCOVERY_QUEUE_URL`
is empty in `.env.example`), because the discovery/download/analysis Lambdas
normally only run in AWS. To exercise the full pipeline locally against a
LocalStack-backed SQS/S3 stack instead, see "Local pipeline development"
below.

## Local pipeline development

In production, `POST /scrape/{ticker}` enqueues a message that flows through
three Lambdas: discovery -> download -> analysis (see `deployment.md` for the
full architecture). By default, none of that runs locally — `docker compose
up` only runs the FastAPI app, so a scrape request just 503s.

To run the full pipeline locally instead, against
[LocalStack](https://www.localstack.cloud/) standing in for SQS/S3:

```bash
docker compose -f docker-compose.yml -f docker-compose.local-pipeline.yml up --build
```

This adds:

- a `localstack` container providing local SQS queues and an S3 bucket;
- a one-shot `pipeline-bootstrap` service that creates them and wires the
  raw-document bucket's `ObjectCreated` notifications to the analysis queue,
  mirroring `infra/template.yaml`'s AWS wiring;
- `discovery-worker`, `download-worker`, and `analysis-worker` containers,
  each running `backend/scripts/local_worker.py` — a small script that long-polls
  its queue and calls the *same* `lambdas/discovery.py` /
  `download.py` / `analysis.py` `handler()` functions AWS invokes, so the
  code under test is identical to what's deployed; only the invocation
  mechanism (a polling loop instead of a one-shot Lambda call) differs.

With this running, `POST /scrape/{ticker}` against `http://localhost:8000`
works end-to-end: it enqueues discovery, which finds documents and enqueues
download, which stores the raw file in the local S3 bucket and (via the S3
notification) enqueues analysis, which runs FinBERT/Groq and writes the
summary/sentiment rows — all visible in Postgres the same way a real AWS run
would leave them.

This is a dev convenience, not a staging environment: there's no CloudFront,
no API Gateway, and no cost controls. Use `infra/README.md`'s staging
deployment to validate anything AWS-specific (IAM, throttling, budgets).

### Verifying it's working

**1. Trigger a scrape.** `POST /scrape/{ticker}` requires an admin session,
so sign up, promote yourself in Postgres, then sign back in:

```bash
curl -c cookies.txt -X POST http://localhost:8000/auth/sign-up \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","name":"You","password":"SomePassword123!"}'

docker compose -f docker-compose.yml -f docker-compose.local-pipeline.yml \
  exec db psql -U user -d spike \
  -c "UPDATE investors SET role = 'admin' WHERE email = 'you@example.com';"

curl -c cookies.txt -X POST http://localhost:8000/auth/sign-in \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"SomePassword123!"}'

curl -b cookies.txt -X POST http://localhost:8000/scrape/CSL \
  -H "Idempotency-Key: manual-check-1"
# {"status":"queued","ticker":"CSL","scrape_run_id":"..."}
```

**2. Watch it move through the pipeline** by following the worker logs —
each stage logs a structured JSON line per message:

```bash
docker compose -f docker-compose.yml -f docker-compose.local-pipeline.yml \
  logs -f discovery-worker download-worker analysis-worker
```

You should see `"event":"completed"` from discovery (with
`documents_queued`), then one `"event":"completed"` per document from
download and again from analysis. `analysis-worker` also logs a couple of
harmless `"event":"permanent_failure","error_code":"invalid_s3_event"`
lines the first time a bucket notification is configured — that's S3's own
automatic test event, not a real message, and the handler correctly drops
it rather than retrying forever.

**3. Check the ground truth in Postgres** — the `scrape_run_id` from step 1:

```bash
docker compose -f docker-compose.yml -f docker-compose.local-pipeline.yml \
  exec db psql -U user -d spike -c \
  "SELECT status, items_found, items_downloaded, items_analyzed, items_failed
   FROM scrape_runs WHERE id = '<scrape_run_id>';"

docker compose -f docker-compose.yml -f docker-compose.local-pipeline.yml \
  exec db psql -U user -d spike -c \
  "SELECT a.title, a.download_status, a.analysis_status, s.sentiment_label
   FROM artifacts a LEFT JOIN artifact_sentiments s ON s.artifact_id = a.id
   WHERE a.scrape_run_id = '<scrape_run_id>';"
```

A healthy run ends with `status = completed` and every artifact showing
`download_status = stored`, `analysis_status = completed`.

**4. Inspect SQS and S3 directly**, if you want to see messages/objects
rather than just logs. The backend image already has `boto3` installed and
is wired to LocalStack, so this needs nothing extra on your host — no AWS
CLI required:

```bash
# Queue depth (should drain to 0 once workers finish processing)
docker compose -f docker-compose.yml -f docker-compose.local-pipeline.yml \
  exec backend python -c "
import boto3
sqs = boto3.client('sqs')
for name in ['discovery', 'download', 'analysis']:
    url = sqs.get_queue_url(QueueName=f'stocks-in-hand-local-{name}')['QueueUrl']
    n = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=['ApproximateNumberOfMessages'])
    print(name, n['Attributes']['ApproximateNumberOfMessages'])
"

# Peek at a message without consuming it (VisibilityTimeout=0)
docker compose -f docker-compose.yml -f docker-compose.local-pipeline.yml \
  exec backend python -c "
import boto3, json
sqs = boto3.client('sqs')
url = sqs.get_queue_url(QueueName='stocks-in-hand-local-download')['QueueUrl']
for m in sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=5, VisibilityTimeout=0).get('Messages', []):
    print(json.loads(m['Body']))
"

# Raw documents actually stored in S3
docker compose -f docker-compose.yml -f docker-compose.local-pipeline.yml \
  exec backend python -c "
import boto3
s3 = boto3.client('s3')
for obj in s3.list_objects_v2(Bucket='stocks-in-hand-local-raw').get('Contents', []):
    print(obj['Key'], obj['Size'])
"
```

If you'd rather use the `aws` CLI from your host instead of `docker compose
exec`, LocalStack's port is published — point it at
`--endpoint-url http://localhost:4566 --region ap-southeast-2` with any
dummy credentials (`AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test`);
LocalStack doesn't validate them.
