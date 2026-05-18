"""Load deterministic mock data into the configured application database.

Run from the backend container:
    python scripts/load_mock_data.py

Or from the repository root:
    python backend/scripts/load_mock_data.py
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401
from app.core.security import hash_password
from app.database.connection import SessionLocal
from app.models.alert import Alert
from app.models.artifact import Artifact
from app.models.artifact_chunk import ArtifactChunk
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.models.artifact_topic import ArtifactTopic
from app.models.information_platform import InformationPlatform
from app.models.investor import Investor
from app.models.market_data import MarketData
from app.models.scrape_run import ScrapeRun
from app.models.ticker import Ticker
from app.models.topic import Topic
from app.models.watchlist import Watchlist
from app.models.watchlist_ticker import WatchlistTicker
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


NOW = datetime.now(timezone.utc).replace(microsecond=0)

TICKERS = [
    {
        "symbol": "BHP",
        "company_name": "BHP Group Limited",
        "sector": "Materials",
        "industry": "Diversified Metals & Mining",
        "market_cap": Decimal("229000000000"),
    },
    {
        "symbol": "CBA",
        "company_name": "Commonwealth Bank of Australia",
        "sector": "Financials",
        "industry": "Banks",
        "market_cap": Decimal("198000000000"),
    },
    {
        "symbol": "CSL",
        "company_name": "CSL Limited",
        "sector": "Health Care",
        "industry": "Biotechnology",
        "market_cap": Decimal("132000000000"),
    },
]

PLATFORMS = [
    {
        "name": "ASX Announcements",
        "platform_type": "exchange_announcement",
        "base_url": "https://www.asx.com.au/markets/trade-our-cash-market/announcements",
        "credibility_score": Decimal("0.98"),
        "scrape_enabled": True,
        "scrape_config": {"source": "mock", "cadence": "15m"},
    },
    {
        "name": "Reddit",
        "platform_type": "forum",
        "base_url": "https://www.reddit.com/r/ASX",
        "credibility_score": Decimal("0.42"),
        "scrape_enabled": False,
        "scrape_config": {"source": "mock"},
    },
]

TOPICS = [
    ("Capital Management", "Dividends, buybacks, and balance-sheet decisions."),
    ("Guidance", "Forward-looking company commentary and outlook changes."),
    ("Operations", "Production, demand, and delivery updates."),
    ("Risk", "Regulatory, macro, and execution risks."),
]

ANNOUNCEMENTS = [
    {
        "ticker": "BHP",
        "title": "BHP quarterly operational review confirms iron ore guidance",
        "category": "Earnings/Guidance",
        "published_offset_days": 0,
        "about": "BHP released a quarterly update covering production volumes, unit costs, and project milestones.",
        "changed": "Iron ore guidance was maintained while copper production improved against the prior quarter.",
        "matters": "Stable guidance supports near-term confidence and gives investors clearer cash-flow expectations.",
        "raw_text": (
            "BHP reported resilient operating performance across core assets. "
            "Iron ore shipments remained within guidance and copper volumes improved sequentially. "
            "Management noted disciplined cost control and no material change to full-year outlook."
        ),
        "topics": ["Guidance", "Operations"],
        "sentiment": "positive",
        "stance": "supportive",
    },
    {
        "ticker": "CBA",
        "title": "CBA trading update notes deposit growth and margin pressure",
        "category": "Trading Update",
        "published_offset_days": 1,
        "about": "CBA provided a trading update across deposits, lending, arrears, and net interest margin.",
        "changed": "Customer deposits grew, but competitive pricing continued to weigh on margin momentum.",
        "matters": "The update frames bank earnings around volume resilience versus margin compression.",
        "raw_text": (
            "Commonwealth Bank reported continued household deposit growth and stable credit quality. "
            "Net interest margin remains under pressure from competition and funding costs. "
            "Arrears remain manageable relative to long-run averages."
        ),
        "topics": ["Guidance", "Risk"],
        "sentiment": "neutral",
        "stance": "balanced",
    },
    {
        "ticker": "CSL",
        "title": "CSL confirms plasma collection recovery and product demand",
        "category": "Market Update",
        "published_offset_days": 2,
        "about": "CSL updated investors on collection volumes, immunoglobulin demand, and manufacturing throughput.",
        "changed": "Collection volumes improved and demand remained strong across core therapies.",
        "matters": "Improved collections can support margin recovery if manufacturing efficiency follows.",
        "raw_text": (
            "CSL reported a continued recovery in plasma collections and steady demand for core therapies. "
            "The company expects operating leverage to improve as throughput normalises. "
            "Management highlighted investment in capacity and patient access."
        ),
        "topics": ["Operations", "Guidance"],
        "sentiment": "positive",
        "stance": "supportive",
    },
    {
        "ticker": "BHP",
        "title": "BHP declares fully franked interim dividend",
        "category": "Dividend",
        "published_offset_days": 5,
        "about": "BHP announced an interim dividend following first-half earnings.",
        "changed": "The board approved a fully franked dividend in line with its payout framework.",
        "matters": "The payout reinforces capital discipline and gives income-focused investors a clear return signal.",
        "raw_text": (
            "The board declared a fully franked interim dividend. "
            "Capital allocation remains focused on balance-sheet strength, shareholder returns, and disciplined growth."
        ),
        "topics": ["Capital Management"],
        "sentiment": "positive",
        "stance": "supportive",
    },
]


def content_hash(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def get_or_create(
    db: Session,
    model: type[Any],
    defaults: dict[str, Any] | None = None,
    **lookup: Any,
):
    instance = db.query(model).filter_by(**lookup).first()
    if instance:
        return instance, False

    values = {**lookup, **(defaults or {})}
    instance = model(**values)
    db.add(instance)
    db.flush()
    return instance, True


def upsert_tickers(db: Session) -> dict[str, Ticker]:
    tickers: dict[str, Ticker] = {}
    for data in TICKERS:
        ticker, _ = get_or_create(
            db,
            Ticker,
            symbol=data["symbol"],
            defaults={key: value for key, value in data.items() if key != "symbol"},
        )
        for key, value in data.items():
            setattr(ticker, key, value)
        tickers[ticker.symbol] = ticker
    return tickers


def upsert_platforms(db: Session) -> dict[str, InformationPlatform]:
    platforms: dict[str, InformationPlatform] = {}
    for data in PLATFORMS:
        platform, _ = get_or_create(
            db,
            InformationPlatform,
            name=data["name"],
            defaults={key: value for key, value in data.items() if key != "name"},
        )
        for key, value in data.items():
            setattr(platform, key, value)
        platforms[platform.name] = platform
    return platforms


def upsert_topics(db: Session) -> dict[str, Topic]:
    topics: dict[str, Topic] = {}
    for name, description in TOPICS:
        topic, _ = get_or_create(db, Topic, name=name, defaults={"description": description})
        topic.description = description
        topics[name] = topic
    return topics


def upsert_announcements(
    db: Session,
    tickers: dict[str, Ticker],
    platforms: dict[str, InformationPlatform],
    topics: dict[str, Topic],
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    asx = platforms["ASX Announcements"]

    for item in ANNOUNCEMENTS:
        ticker = tickers[item["ticker"]]
        published_at = NOW - timedelta(days=item["published_offset_days"])
        hash_value = content_hash("mock-asx", item["ticker"], item["title"])
        artifact, _ = get_or_create(
            db,
            Artifact,
            content_hash=hash_value,
            defaults={
                "ticker_id": ticker.id,
                "platform_id": asx.id,
                "source_type": "asx_announcement",
                "artifact_type": "company_announcement",
                "title": item["title"],
                "url": (
                    "https://www.asx.com.au/asx/v2/statistics/"
                    f"displayAnnouncement.do?mock={hash_value[:12]}"
                ),
                "raw_text": item["raw_text"],
                "artifact_metadata": {
                    "category": item["category"],
                    "about": item["about"],
                    "changed": item["changed"],
                    "matters": item["matters"],
                    "source": "mock_seed",
                },
                "published_at": published_at,
                "credibility_label": "official",
            },
        )
        artifact.ticker_id = ticker.id
        artifact.platform_id = asx.id
        artifact.source_type = "asx_announcement"
        artifact.artifact_type = "company_announcement"
        artifact.title = item["title"]
        artifact.url = (
            "https://www.asx.com.au/asx/v2/statistics/"
            f"displayAnnouncement.do?mock={hash_value[:12]}"
        )
        artifact.raw_text = item["raw_text"]
        artifact.artifact_metadata = {
            "category": item["category"],
            "about": item["about"],
            "changed": item["changed"],
            "matters": item["matters"],
            "source": "mock_seed",
        }
        artifact.published_at = published_at
        artifact.is_duplicate = False
        artifact.credibility_label = "official"

        chunk, _ = get_or_create(
            db,
            ArtifactChunk,
            artifact_id=artifact.id,
            chunk_index=0,
            defaults={
                "chunk_text": item["raw_text"],
                "token_count": len(item["raw_text"].split()),
            },
        )
        chunk.chunk_text = item["raw_text"]
        chunk.token_count = len(item["raw_text"].split())

        summary, _ = get_or_create(
            db,
            ArtifactSummary,
            artifact_id=artifact.id,
            defaults={
                "summary_text": item["about"],
                "model_used": "mock-seed",
                "prompt_version": "mock-v1",
                "confidence_score": Decimal("0.86"),
            },
        )
        summary.summary_text = item["about"]

        sentiment, _ = get_or_create(
            db,
            ArtifactSentiment,
            artifact_id=artifact.id,
            defaults={
                "sentiment_label": item["sentiment"],
                "stance": item["stance"],
                "confidence_score": Decimal("0.78"),
                "model_used": "mock-seed",
            },
        )
        sentiment.sentiment_label = item["sentiment"]
        sentiment.stance = item["stance"]

        for topic_name in item["topics"]:
            get_or_create(
                db,
                ArtifactTopic,
                artifact_id=artifact.id,
                topic_id=topics[topic_name].id,
                defaults={"confidence_score": Decimal("0.82")},
            )

        artifacts.append(artifact)

    return artifacts


def upsert_market_data(db: Session, tickers: dict[str, Ticker]) -> None:
    base_prices = {"BHP": Decimal("43.20"), "CBA": Decimal("118.40"), "CSL": Decimal("284.10")}
    for symbol, ticker in tickers.items():
        base = base_prices[symbol]
        for days_ago in range(5):
            price_date = date.today() - timedelta(days=days_ago)
            close_price = base + Decimal(days_ago) * Decimal("0.35")
            market_data, _ = get_or_create(
                db,
                MarketData,
                ticker_id=ticker.id,
                price_date=price_date,
                defaults={
                    "open_price": close_price - Decimal("0.20"),
                    "high_price": close_price + Decimal("0.55"),
                    "low_price": close_price - Decimal("0.65"),
                    "close_price": close_price,
                    "adjusted_close_price": close_price,
                    "volume": 2_000_000 + days_ago * 175_000,
                },
            )
            market_data.close_price = close_price
            market_data.adjusted_close_price = close_price


def upsert_demo_investor(db: Session, tickers: dict[str, Ticker]) -> Investor:
    investor, created = get_or_create(
        db,
        Investor,
        email="demo@stonks.com",
        defaults={
            "username": "Demo Investor",
            "hashed_password": hash_password("password123"),
            "role": "user",
        },
    )
    investor.username = "Demo Investor"
    investor.role = "user"
    if created or not investor.hashed_password:
        investor.hashed_password = hash_password("password123")

    watchlist, _ = get_or_create(
        db,
        Watchlist,
        investor_id=investor.id,
        name="Demo Watchlist",
    )

    for symbol in ("BHP", "CBA", "CSL"):
        get_or_create(
            db,
            WatchlistTicker,
            watchlist_id=watchlist.id,
            ticker_id=tickers[symbol].id,
        )

    alerts = [
        (
            "BHP",
            "announcement",
            "BHP guidance maintained",
            "New ASX update confirms full-year guidance.",
            "info",
        ),
        (
            "CBA",
            "risk",
            "CBA margin pressure",
            "Trading update notes competitive pressure on margins.",
            "warning",
        ),
        (
            "CSL",
            "momentum",
            "CSL collection recovery",
            "Plasma collection volumes continue to recover.",
            "success",
        ),
    ]
    for symbol, alert_type, title, message, severity in alerts:
        alert, _ = get_or_create(
            db,
            Alert,
            investor_id=investor.id,
            ticker_id=tickers[symbol].id,
            title=title,
            defaults={
                "alert_type": alert_type,
                "message": message,
                "severity": severity,
                "is_read": False,
            },
        )
        alert.alert_type = alert_type
        alert.message = message
        alert.severity = severity

    return investor


def upsert_scrape_runs(
    db: Session,
    tickers: dict[str, Ticker],
    platforms: dict[str, InformationPlatform],
) -> None:
    asx = platforms["ASX Announcements"]
    for symbol, ticker in tickers.items():
        get_or_create(
            db,
            ScrapeRun,
            platform_id=asx.id,
            ticker_id=ticker.id,
            status="completed",
            defaults={
                "started_at": NOW - timedelta(minutes=20),
                "finished_at": NOW - timedelta(minutes=18),
                "items_found": 4,
                "items_saved": 4,
            },
        )


def load_mock_data() -> dict[str, int]:
    with SessionLocal() as db:
        tickers = upsert_tickers(db)
        platforms = upsert_platforms(db)
        topics = upsert_topics(db)
        artifacts = upsert_announcements(db, tickers, platforms, topics)
        upsert_market_data(db, tickers)
        upsert_demo_investor(db, tickers)
        upsert_scrape_runs(db, tickers, platforms)
        db.commit()

        return {
            "tickers": len(tickers),
            "platforms": len(platforms),
            "topics": len(topics),
            "announcements": len(artifacts),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load mock data into the StonksInHand database."
    )
    parser.parse_args()

    try:
        counts = load_mock_data()
    except SQLAlchemyError as exc:
        print(f"Failed to load mock data: {exc}", file=sys.stderr)
        return 1

    print("Mock data loaded:")
    for label, count in counts.items():
        print(f"  {label}: {count}")
    print("Demo sign-in: demo@stonks.com / password123")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
