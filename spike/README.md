# StonksInHand — Tech Spike

**Next.js → FastAPI → FinBERT (HuggingFace) → PostgreSQL**, all in Docker.

## Quickstart

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend (Swagger) | http://localhost:8000/docs |

> **Note:** First startup downloads the FinBERT model (~500MB). Subsequent starts are instant.

## Stack

| | Technology |
|---|---|
| Frontend | Next.js 14 |
| Backend | FastAPI (Python 3.11) |
| Sentiment | HuggingFace `ProsusAI/finbert` |
| Database | PostgreSQL 15 |
| Container | Docker Compose |
