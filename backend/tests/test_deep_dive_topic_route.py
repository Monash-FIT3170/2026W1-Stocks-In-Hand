"""Topic validation and forwarding without a database or LLM."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import ticker
from app.database.connection import get_db


@pytest.mark.parametrize("topic", ["litigation", "regulation", "", "  "])
def test_deep_dive_forwards_valid_topics(monkeypatch, topic):
    db = object()
    read = Mock(return_value=[])
    monkeypatch.setattr(ticker.ticker_records, "read_deep_dive", read)
    app = FastAPI()
    app.include_router(ticker.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.get("/tickers/symbol/BHP/deep-dive-timeline", params={"topic": topic})
    assert response.status_code == 200
    assert response.json() == []
    read.assert_called_once_with(db, "BHP", topic=topic.strip() or None)


def test_deep_dive_rejects_unknown_topics_before_querying(monkeypatch):
    read = Mock()
    monkeypatch.setattr(ticker.ticker_records, "read_deep_dive", read)
    app = FastAPI()
    app.include_router(ticker.router)
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        response = client.get("/tickers/symbol/BHP/deep-dive-timeline?topic=astrology")
    assert response.status_code == 422
    read.assert_not_called()
