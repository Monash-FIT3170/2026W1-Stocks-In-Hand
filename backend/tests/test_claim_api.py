"""Claim evidence must survive public API serialization and feed mapping."""

from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import artifact as routes
from app.api.routes import ticker as ticker_routes
from app.crud.announcement import _announcement_from_artifact
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.services.traceability import bind_claim_evidence


def stored_artifact():
    metadata = {
        "about": "Revenue increased.", "changed": "Revenue rose 12%.",
        "confirmed_facts": ["Revenue rose 12%."], "speculation": [],
        "claim_evidence": [{"field": "confirmed_facts", "index": 0, "quote": "Revenue increased by 12%."}],
    }
    raw = "Revenue increased by 12%."
    metadata["claim_evidence"] = bind_claim_evidence(metadata, raw)
    return Artifact(
        id=uuid4(), ticker=Ticker(id=uuid4(), symbol="BHP", company_name="BHP Group", exchange="ASX"),
        title="Results", source_type="asx_announcement", artifact_type="half_year_results",
        url="https://example.test/listing", document_url="https://example.test/results.pdf",
        published_at=datetime(2026, 10, 1, tzinfo=timezone.utc), raw_text=raw,
        artifact_metadata=metadata,
    )


def test_claim_endpoint_serializes_provenance_and_handles_missing_artifacts(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_db] = lambda: None
    artifact = stored_artifact()
    monkeypatch.setattr(routes.crud, "get_artifact", lambda _db, artifact_id: artifact if artifact_id == artifact.id else None)
    client = TestClient(app)
    response = client.get(f"/artifacts/{artifact.id}/claims")
    assert response.status_code == 200
    fact = next(item for item in response.json() if item["field"] == "confirmed_facts")
    assert fact["status"] == "quoted"
    assert fact["source"]["artifact_id"] == str(artifact.id)
    assert fact["source"]["url"] == artifact.document_url
    assert fact["evidence"][0]["quote"] == artifact.raw_text
    assert client.get(f"/artifacts/{uuid4()}/claims").status_code == 404
    assert client.get("/artifacts/not-a-uuid/claims").status_code == 422


def test_global_feed_preserves_claim_evidence():
    artifact = stored_artifact()
    result = _announcement_from_artifact(artifact).model_dump(mode="json")
    fact = next(item for item in result["claims"] if item["field"] == "confirmed_facts")
    assert fact["evidence"][0]["quote"] == artifact.raw_text


def test_ticker_feeds_and_brief_expose_same_claim_evidence(monkeypatch):
    artifact = stored_artifact()
    monkeypatch.setattr(ticker_routes, "_ensure_default_tickers", lambda _db: None)
    monkeypatch.setattr(ticker_routes.crud, "get_ticker_by_symbol", lambda *_args, **_kwargs: artifact.ticker)
    monkeypatch.setattr(ticker_routes, "_live_quote", lambda _symbol: None)
    monkeypatch.setattr(ticker_routes, "_ticker_artifacts", lambda *_args, **_kwargs: [artifact])
    monkeypatch.setattr(ticker_routes, "_latest_sentiment_for_ticker", lambda *_args: None)
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    overview = ticker_routes.get_ticker_brief("BHP", db)["overview"]
    news = ticker_routes.get_ticker_news_feed("BHP", db)[0]
    timeline = ticker_routes.get_ticker_deep_dive_timeline("BHP", db)[0]
    assert overview["claims"] == news["claims"] == timeline["claims"]
    assert any(item["status"] == "quoted" for item in overview["claims"])


def test_category_signals_keep_constituent_claim_sources_distinct():
    from app.api.routes.category_sentiment import _aggregate_stored_category
    from app.models.artifact_sentiment import ArtifactSentiment
    from app.schemas.category_sentiment import CategorySentimentResult

    first, second = stored_artifact(), stored_artifact()
    second.document_url = "https://example.test/second-report.pdf"
    rows = [(item, ArtifactSentiment(
        sentiment_label="positive", confidence_score=0.9,
        model_used="test", created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )) for item in (first, second)]
    payload = CategorySentimentResult(**_aggregate_stored_category("revenue", rows)).model_dump(mode="json")
    facts = [claim for claim in payload["claims"] if claim["field"] == "confirmed_facts"]
    assert len(facts) == 2
    assert facts[0]["id"] != facts[1]["id"]
    assert {claim["source"]["url"] for claim in facts} == {first.document_url, second.document_url}
    assert all(claim["status"] == "quoted" for claim in facts)
