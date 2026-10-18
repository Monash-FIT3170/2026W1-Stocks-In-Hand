"""Content topic tagging: decide what an artifact is about, then record and cluster it.

``decide_topics`` is the one place an artifact's topics are decided. The
rules in ``parsing.content_topics`` always run. With
``CONTENT_TOPICS_LLM_ENABLED`` on and an LLM switched on, the LLM decides,
with the rules' topics offered as hints:

- a topic the LLM and the rules agree on gains ``AGREEMENT_BONUS``;
- a topic only the rules found is kept when its rules score reaches
  ``STRONG_RULES_SCORE``, which only a category hint with supporting words
  reaches, so a half-year result is never left without its earnings topic;
- a topic whose quotation is not in the source keeps a reduced confidence
  (``generation.kinds.UNSUPPORTED_TOPIC_FACTOR``).

With no LLM, or an answer that cannot be used, the rules decide. Either way
only topics of at least ``CONTENT_TOPIC_MIN_CONFIDENCE`` are recorded.

``PostgresContentTopics`` is the analysis worker's topic port: it reads the
artifact, decides its topics and records them in its own short session.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import content_topic as content_topic_crud
from app.crud.content_topic import TopicRecord
from app.models.artifact import Artifact
from app.services import generation
from app.services.generation.providers import TextProvider
from parsing.content_topics import (
    RULES_VERSION,
    TOPICS,
    TopicInput,
    TopicMatch,
    detect_topics,
)

LOGGER = logging.getLogger(__name__)

AGREEMENT_BONUS = 0.1
STRONG_RULES_SCORE = 0.8
# The topics, with what each covers, as the LLM prompt lists them.
TOPIC_DESCRIPTIONS: tuple[tuple[str, str], ...] = tuple(
    (topic.identifier, topic.description) for topic in TOPICS
)

SessionScope = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class TopicDecision:
    """The topics decided for one artifact and what decided them."""

    topics: tuple[TopicRecord, ...]
    method: str
    version: str
    model: str | None
    # Why the LLM's answer was not used, when it was asked and failed.
    llm_error: str | None = None


def decide_topics(
    source: TopicInput,
    *,
    provider: TextProvider | None = None,
    use_llm: bool | None = None,
    min_confidence: float | None = None,
) -> TopicDecision:
    """The artifact's topics, decided by the LLM with rule hints or by the rules alone."""
    use_llm = settings.CONTENT_TOPICS_LLM_ENABLED if use_llm is None else use_llm
    floor = settings.CONTENT_TOPIC_MIN_CONFIDENCE if min_confidence is None else min_confidence
    rules = detect_topics(source)
    llm_error: str | None = None
    if use_llm and source.text.strip():
        try:
            generated = generation.generate(
                generation.TopicTagging(
                    title=source.title,
                    source_type=source.source_type or "unknown",
                    raw_text=source.text,
                    topics=TOPIC_DESCRIPTIONS,
                    hints=tuple(match.topic for match in rules),
                ),
                provider=provider,
            )
        # A malformed answer (ValueError) or a failed call (RuntimeError)
        # leaves the rules to decide, so topics never fail an analysis.
        except (ValueError, RuntimeError) as exc:
            llm_error = type(exc).__name__
            LOGGER.warning("content topic tagging fell back to the rules: %s", llm_error)
        else:
            if isinstance(generated, generation.Generated):
                return TopicDecision(
                    topics=_floor(_with_llm(generated.value, rules), floor),
                    method="llm",
                    version=generated.prompt_version,
                    model=generated.model,
                )
    return TopicDecision(
        topics=_floor(tuple(_from_rules(match) for match in rules), floor),
        method="rules",
        version=RULES_VERSION,
        model=None,
        llm_error=llm_error,
    )


def _with_llm(
    answer: list[dict[str, object]],
    rules: tuple[TopicMatch, ...],
) -> tuple[TopicRecord, ...]:
    by_rule = {match.topic: match for match in rules}
    records: list[TopicRecord] = []
    for entry in answer:
        topic = str(entry["topic"])
        confidence = float(entry["confidence"])  # type: ignore[arg-type]
        rule = by_rule.get(topic)
        if rule is not None:
            confidence = min(1.0, confidence + AGREEMENT_BONUS)
        passage = entry.get("passage")
        event = entry.get("event")
        records.append(
            TopicRecord(
                topic=topic,
                confidence=round(confidence, 4),
                method="llm",
                evidence=(
                    passage
                    if isinstance(passage, str) and passage
                    else (rule.evidence if rule is not None else None)
                ),
                event_label=event if isinstance(event, str) and event else None,
            )
        )
    chosen = {record.topic for record in records}
    records.extend(
        _from_rules(match)
        for match in rules
        if match.topic not in chosen and match.score >= STRONG_RULES_SCORE
    )
    return tuple(records)


def _from_rules(match: TopicMatch) -> TopicRecord:
    return TopicRecord(
        topic=match.topic,
        confidence=match.score,
        method="rules",
        evidence=match.evidence,
        event_label=None,
    )


def _floor(records: tuple[TopicRecord, ...], floor: float) -> tuple[TopicRecord, ...]:
    kept = [record for record in records if record.confidence >= floor]
    return tuple(sorted(kept, key=lambda record: (-record.confidence, record.topic)))


def topic_input(artifact: Artifact) -> TopicInput:
    """What the rules and the LLM read about a stored artifact."""
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    classification = metadata.get("classification")
    category = (
        classification.get("primary_category") if isinstance(classification, dict) else None
    ) or metadata.get("category")
    return TopicInput(
        title=(artifact.title or "").strip(),
        text=(artifact.raw_text or "").replace("\x00", "").strip(),
        category=category if isinstance(category, str) else None,
        source_type=artifact.source_type,
    )


def tag_artifact(
    db: Session,
    artifact: Artifact,
    *,
    provider: TextProvider | None = None,
    use_llm: bool | None = None,
) -> TopicDecision:
    """Decide the stored artifact's topics, record and cluster them, and commit."""
    decision = decide_topics(topic_input(artifact), provider=provider, use_llm=use_llm)
    content_topic_crud.record_topics(
        db,
        artifact,
        decision.topics,
        version=decision.version,
        method=decision.method,
        model=decision.model,
        window_days=settings.CONTENT_TOPIC_CLUSTER_WINDOW_DAYS,
    )
    db.commit()
    return decision


class PostgresContentTopics:
    """The analysis worker's content topic port, over its own short sessions."""

    def __init__(self, session_scope: SessionScope) -> None:
        self._session_scope = session_scope

    def tag(self, artifact_id: UUID, *, provider: TextProvider | None = None) -> Any:
        """Tag one analysed artifact. Returns its decision, or None when it does not exist.

        No session is held while the LLM answers: the artifact is read in
        one session and the topics are recorded in another.
        """
        with self._session_scope() as db:
            artifact = db.get(Artifact, artifact_id)
            if artifact is None:
                return None
            source = topic_input(artifact)
        decision = decide_topics(source, provider=provider)
        with self._session_scope() as db:
            artifact = db.get(Artifact, artifact_id)
            if artifact is None:
                return None
            content_topic_crud.record_topics(
                db,
                artifact,
                decision.topics,
                version=decision.version,
                method=decision.method,
                model=decision.model,
                window_days=settings.CONTENT_TOPIC_CLUSTER_WINDOW_DAYS,
            )
            db.commit()
        return decision
