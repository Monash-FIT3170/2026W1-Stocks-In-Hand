"""Relevance policy and maintenance tests with no database or external LLM."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.generation.providers import ScriptedProvider
from app.services.llm_errors import LLMUnavailableError
from lambdas.artifact_analysis import AnalysisPorts, ArtifactFacts, FixedSentiment, assess_feed_eligibility, summarise
from tools import reassess_reddit_feed as tool


def facts(*, matched=True, eligible=None):
    return SimpleNamespace(source_type="reddit", has_ticker_match=matched, feed_eligible=eligible)


@pytest.mark.parametrize("title", ["Income etfs", "Am i in the right direction at 19 years old?"])
def test_unmatched_advice_is_rejected_without_generation(title):
    provider = ScriptedProvider([])
    ports = AnalysisPorts(records=Mock(), scorer=FixedSentiment("neutral"), provider=provider)
    result = assess_feed_eligibility(facts(matched=False, eligible=True), title, "General portfolio advice", ports)
    assert result["feed_eligible"] is False
    assert provider.calls == []


def test_matched_company_post_is_assessed_with_advice_exclusions():
    provider = ScriptedProvider([json.dumps({"feed_eligible": True, "eligibility_confidence": 0.94, "reason": "Company production research"})])
    ports = AnalysisPorts(records=Mock(), scorer=FixedSentiment("neutral"), provider=provider)
    result = assess_feed_eligibility(facts(), "BHP quarterly output", "BHP reported copper output growth", ports)
    assert result["feed_eligible"] is True
    assert "portfolio reviews" in provider.calls[0].prompt
    assert ports.scorer.scored == []


def test_low_confidence_company_match_is_not_approved():
    provider = ScriptedProvider([json.dumps({"feed_eligible": True, "eligibility_confidence": 0.5, "reason": "Uncertain relevance"})])
    ports = AnalysisPorts(records=Mock(), scorer=FixedSentiment("neutral"), provider=provider)
    assert assess_feed_eligibility(facts(), "BHP", "An ambiguous mention", ports)["feed_eligible"] is False


def test_reassessment_dry_run_never_calls_llm_or_writes(monkeypatch):
    post = SimpleNamespace(id=uuid.uuid4(), title="Income etfs", url="https://reddit.com/r/ASX/comments/example")
    monkeypatch.setattr(tool, "select_candidates", lambda *args, **kwargs: [post])
    db = Mock()
    provider = ScriptedProvider([])
    result = tool.run_reassessment(db, provider=provider)
    assert result["selected"] == 1
    assert result["updated"] == 0
    assert result["records"][0]["url"] == post.url
    assert provider.calls == []
    db.commit.assert_not_called()
    db.query.assert_not_called()


@pytest.mark.parametrize("limit", [0, -1, 201])
def test_reassessment_rejects_unbounded_batches(limit):
    with pytest.raises(ValueError, match="limit"):
        tool.select_candidates(Mock(), limit=limit)


def stored_facts(artifact_id):
    return ArtifactFacts(
        artifact_id=artifact_id, kind="discussion", source_type="reddit",
        source_adapter="reddit", ticker="BHP", run_id=None,
        title="BHP copper update", raw_text="BHP reported higher copper output.",
        artifact_type="reddit_post", category="user_discussion", extracted_data={},
        source_name="Reddit", filename=None, has_ticker_match=True,
        feed_eligible=None, completed=True, document=None,
    )


@pytest.mark.parametrize("accepted", [True, False])
def test_reassessment_preserves_company_link_and_other_metadata(monkeypatch, accepted):
    post = SimpleNamespace(id=uuid.uuid4(), title="BHP copper update", url="https://reddit.com/r/ASX/comments/bhp", ticker_id=uuid.uuid4(), artifact_metadata={"score": 42})
    original = (post.url, post.ticker_id)
    monkeypatch.setattr(tool, "select_candidates", lambda *args, **kwargs: [post])
    records = Mock()
    records.facts.return_value = stored_facts(post.id)
    monkeypatch.setattr(tool, "PostgresAnalysisRecords", lambda scope: records)
    db = Mock()
    db.query.return_value.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = post
    provider = ScriptedProvider([json.dumps({"feed_eligible": accepted, "eligibility_confidence": 0.94, "reason": "Assessed research relevance"})])
    result = tool.run_reassessment(db, apply=True, provider=provider)
    assert result["updated"] == 1
    assert result["failed"] == []
    assert post.artifact_metadata["feed_eligible"] is accepted
    assert post.artifact_metadata["score"] == 42
    assert (post.url, post.ticker_id) == original
    db.commit.assert_called_once()


def test_failed_reassessment_does_not_change_the_saved_decision(monkeypatch):
    post = SimpleNamespace(id=uuid.uuid4(), title="BHP", url="https://reddit.com/example")
    monkeypatch.setattr(tool, "select_candidates", lambda *args, **kwargs: [post])
    records = Mock()
    records.facts.return_value = stored_facts(post.id)
    monkeypatch.setattr(tool, "PostgresAnalysisRecords", lambda scope: records)
    db = Mock()
    result = tool.run_reassessment(db, apply=True, provider=ScriptedProvider([LLMUnavailableError("disabled")]))
    assert result["updated"] == 0
    assert len(result["failed"]) == 1
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_direct_resummary_rejects_advice_before_summary_generation():
    records = Mock()
    records.facts.return_value = stored_facts(uuid.uuid4())
    provider = ScriptedProvider([json.dumps({"feed_eligible": False, "eligibility_confidence": 0.99, "reason": "General portfolio advice"})])
    ports = AnalysisPorts(records=records, scorer=FixedSentiment("neutral"), provider=provider)
    outcome = summarise(records.facts.return_value.artifact_id, ports)
    assert "excluded" in outcome.reason
    assert len(provider.calls) == 1
    records.record_summary.assert_not_called()
