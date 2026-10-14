"""The artifact summary module, recording and reading summaries on Postgres.

``record`` replaces both stores of a summary, the top-level metadata keys and
the artifact's one ``artifact_summaries`` row, inside the caller's
transaction. ``read`` gives the summary back, recovering older records that
kept only the joined text.
"""

import threading
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine, create_engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.crud.artifact import store_artifact_analysis
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.services import artifact_summary
from app.services.artifact_summary import EmptySummary, Summary
from app.status import AnalysisStatus

ANSWER = {
    "summary": "The company confirmed its dividend timetable.",
    "about": "The filing explains dividend timing.",
    "changed": "The payment date was confirmed.",
    "matters": "Investors can plan income timing.",
    "confirmed_facts": ["The payment date is 2 January 2040."],
    "speculation": ["The dividend may affect future income expectations."],
}
MODEL = "scripted:test-model"
PROMPT_VERSION = "llm-announcement-summary-v3"


@pytest.fixture()
def engine() -> Iterator[Engine]:
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"Database is not available: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    # SessionLocal does not autoflush. Matching it means these tests pass only
    # when record flushes the caller's pending changes itself.
    session = sessionmaker(bind=connection, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _new_announcement(**metadata) -> Artifact:
    return Artifact(
        source_type="asx_announcement",
        artifact_type="dividend_announcement",
        title="Dividend update",
        raw_text="The company confirmed a dividend payment date.",
        content_hash=f"summary-test-{uuid.uuid4()}",
        artifact_metadata=metadata or None,
    )


def _announcement(db: Session, **metadata) -> Artifact:
    artifact = _new_announcement(**metadata)
    db.add(artifact)
    db.commit()
    return artifact


def _summary(**fields) -> Summary:
    return artifact_summary.from_answer(
        {**ANSWER, **fields},
        model=MODEL,
        prompt_version=PROMPT_VERSION,
    )


def _rows(db: Session, artifact_id: uuid.UUID) -> list[ArtifactSummary]:
    return list(
        db.scalars(
            select(ArtifactSummary).where(ArtifactSummary.artifact_id == artifact_id)
        )
    )


def _stored(
    metadata: dict | None = None,
    summary_text: str | None = None,
    source_type: str = "asx_announcement",
) -> Artifact:
    """An unsaved artifact holding a summary the way older code stored it."""
    artifact = Artifact(
        source_type=source_type,
        artifact_type="asx_announcement_other",
        artifact_metadata=metadata,
    )
    if summary_text is not None:
        artifact.summaries.append(
            ArtifactSummary(summary_text=summary_text, model_used="bedrock:legacy")
        )
    return artifact


def test_a_recorded_summary_reads_back_with_its_model_and_prompt_version(
    db_session: Session,
) -> None:
    artifact = _announcement(db_session)

    recorded = artifact_summary.record(db_session, artifact, _summary())
    db_session.commit()

    summary = artifact_summary.read(artifact)
    assert summary == _summary()
    assert summary.lines == {key: ANSWER[key] for key in artifact_summary.TEXT_LINES}
    assert summary.confirmed_facts == ("The payment date is 2 January 2040.",)
    assert summary.speculation == ("The dividend may affect future income expectations.",)
    assert (summary.model, summary.prompt_version) == (MODEL, PROMPT_VERSION)
    [row] = _rows(db_session, artifact.id)
    assert row.id == recorded.summary_id
    assert row.summary_text == "\n\n".join(
        ANSWER[key] for key in artifact_summary.TEXT_LINES
    )


def test_recording_again_replaces_the_one_summary_row(db_session: Session) -> None:
    artifact = _announcement(db_session)
    first = artifact_summary.record(db_session, artifact, _summary())

    second = artifact_summary.record(
        db_session,
        artifact,
        _summary(summary="The company revised its dividend timetable."),
    )
    db_session.commit()

    [row] = _rows(db_session, artifact.id)
    assert row.id == first.summary_id == second.summary_id
    assert row.summary_text.startswith("The company revised its dividend timetable.")


def test_recording_removes_lines_and_lists_the_new_summary_lacks(
    db_session: Session,
) -> None:
    artifact = _announcement(db_session)
    artifact_summary.record(db_session, artifact, _summary())

    artifact_summary.record(
        db_session,
        artifact,
        artifact_summary.from_answer(
            {key: ANSWER[key] for key in ("summary", "about", "matters")},
            model=MODEL,
            prompt_version="llm-news-summary-v2",
        ),
    )
    db_session.commit()

    summary = artifact_summary.read(artifact)
    assert summary.lines == {key: ANSWER[key] for key in ("summary", "about", "matters")}
    assert not summary.is_classified
    assert summary.prompt_version == "llm-news-summary-v2"
    assert not {"changed", "confirmed_facts", "speculation"} & set(
        artifact.artifact_metadata
    )


def test_a_summary_recorded_in_a_rolled_back_savepoint_leaves_nothing(
    db_session: Session,
) -> None:
    artifact = _announcement(db_session, category="DividendAnnouncement")
    savepoint = db_session.begin_nested()

    artifact_summary.record(db_session, artifact, _summary())
    savepoint.rollback()

    assert artifact_summary.read(artifact) is None
    assert artifact.artifact_metadata == {"category": "DividendAnnouncement"}
    assert _rows(db_session, artifact.id) == []


def test_recording_keeps_the_callers_unflushed_metadata(db_session: Session) -> None:
    artifact = _announcement(db_session, category="DividendAnnouncement")
    artifact.artifact_metadata = {**artifact.artifact_metadata, "page_count": 2}

    artifact_summary.record(db_session, artifact, _summary())
    db_session.commit()

    assert artifact.artifact_metadata == {
        "category": "DividendAnnouncement",
        "page_count": 2,
        **ANSWER,
    }


def test_a_summary_without_a_text_line_is_not_recorded(db_session: Session) -> None:
    artifact = _announcement(db_session, category="DividendAnnouncement")

    with pytest.raises(EmptySummary):
        artifact_summary.record(
            db_session,
            artifact,
            artifact_summary.from_answer(
                {"summary": "  ", "confirmed_facts": ["A claim."], "speculation": []},
                model=MODEL,
                prompt_version=PROMPT_VERSION,
            ),
        )
    db_session.commit()

    assert artifact.artifact_metadata == {"category": "DividendAnnouncement"}
    assert _rows(db_session, artifact.id) == []


def test_concurrent_first_records_leave_one_row_with_the_second_summary(
    engine: Engine,
) -> None:
    with Session(engine) as db:
        artifact = _new_announcement()
        db.add(artifact)
        db.commit()
        artifact_id = artifact.id
    errors: list[Exception] = []

    def second_writer() -> None:
        try:
            with Session(engine) as db:
                artifact_summary.record(
                    db,
                    db.get(Artifact, artifact_id),
                    _summary(summary="The second writer's summary."),
                )
                db.commit()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            errors.append(exc)

    first_writer = Session(engine)
    second = threading.Thread(target=second_writer)
    try:
        artifact_summary.record(
            first_writer,
            first_writer.get(Artifact, artifact_id),
            _summary(summary="The first writer's summary.", confirmed_facts=["Old."]),
        )
        second.start()
        second.join(timeout=0.5)
        # The second writer waits on the first writer's lock on the artifact row.
        assert second.is_alive()
        first_writer.commit()
        second.join(timeout=10)

        assert errors == []
        with Session(engine) as db:
            [row] = _rows(db, artifact_id)
            assert row.summary_text.startswith("The second writer's summary.")
            assert artifact_summary.read(db.get(Artifact, artifact_id)) == _summary(
                summary="The second writer's summary."
            )
    finally:
        first_writer.close()
        if second.ident is not None:
            second.join(timeout=10)
        with Session(engine) as db:
            db.execute(delete(ArtifactSummary).where(ArtifactSummary.artifact_id == artifact_id))
            db.execute(delete(Artifact).where(Artifact.id == artifact_id))
            db.commit()


def _claim_evidence(values) -> list | None:
    evidence = values.get("claim_evidence")
    return evidence if isinstance(evidence, list) else None


def test_a_registered_extension_round_trips_and_other_keys_are_dropped(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_summary,
        "EXTENSIONS",
        (artifact_summary.SummaryExtension("claim_evidence", _claim_evidence),),
    )
    artifact = _announcement(db_session)
    evidence = [{"text": "The payment date is 2 January 2040.", "passage": 1}]

    artifact_summary.record(
        db_session,
        artifact,
        _summary(claim_evidence=evidence, tone="upbeat"),
    )
    db_session.commit()

    assert artifact_summary.read(artifact).extensions == {"claim_evidence": evidence}
    assert artifact.artifact_metadata["claim_evidence"] == evidence
    assert "tone" not in artifact.artifact_metadata


def test_storing_an_analysis_twice_keeps_one_summary_and_one_sentiment(
    db_session: Session,
) -> None:
    artifact = _announcement(db_session, category="UNKNOWN")
    analysis = {
        "raw_text": "Stored filing text.",
        "metadata": {"page_count": 2},
        "summary": _summary(),
        "sentiment": {
            "sentiment_label": "positive",
            "confidence_score": 0.9,
            "model_used": "test-finbert",
        },
    }

    for _ in range(2):
        store_artifact_analysis(db_session, artifact_id=artifact.id, **analysis)

    assert artifact.raw_text == "Stored filing text."
    assert artifact.artifact_metadata == {"category": "UNKNOWN", "page_count": 2, **ANSWER}
    assert artifact_summary.read(artifact) == _summary()
    assert len(_rows(db_session, artifact.id)) == 1
    assert (
        db_session.query(ArtifactSentiment)
        .filter(ArtifactSentiment.artifact_id == artifact.id)
        .count()
        == 1
    )


def test_an_answer_is_cleaned_before_it_is_kept() -> None:
    summary = artifact_summary.from_answer(
        {
            "summary": "  The company confirmed its dividend timetable.  ",
            "about": "",
            "changed": 3,
            "confirmed_facts": [
                " The payment   date was set. ",
                "The payment date was set.",
                None,
                "",
                7,
            ],
            "speculation": "Not a list.",
        },
        model=MODEL,
        prompt_version=PROMPT_VERSION,
    )

    assert summary.lines == {"summary": "The company confirmed its dividend timetable."}
    assert summary.confirmed_facts == ("The payment date was set.",)
    assert summary.speculation is None
    assert not summary.is_classified


def test_missing_lines_are_recovered_from_four_paragraph_text() -> None:
    summary = artifact_summary.read(
        _stored({"about": "The metadata line."}, "One.\n\nTwo.\n\nThree.\n\nFour.")
    )

    assert summary.lines == {
        "summary": "One.",
        "about": "The metadata line.",
        "changed": "Three.",
        "matters": "Four.",
    }
    assert summary.model == "bedrock:legacy"


@pytest.mark.parametrize("text", ["One paragraph.", "One.\n\nTwo.\n\nThree."])
def test_text_that_is_not_four_paragraphs_is_not_split(text: str) -> None:
    summary = artifact_summary.read(_stored({"about": "The metadata line."}, text))

    assert summary.lines == {"about": "The metadata line."}


def test_text_with_no_line_beside_it_becomes_the_summary_line() -> None:
    summary = artifact_summary.read(_stored(None, "One.\n\nTwo.\n\nThree."))

    assert summary.lines == {"summary": "One.\n\nTwo.\n\nThree."}


def test_a_clarity_value_that_is_not_a_list_counts_as_missing() -> None:
    summary = artifact_summary.read(
        _stored(
            {
                "about": "The metadata line.",
                "confirmed_facts": "A malformed legacy value.",
                "speculation": [],
            }
        )
    )

    assert summary.confirmed_facts is None
    assert summary.speculation == ()
    assert not summary.is_classified


def test_an_artifact_without_a_summary_reads_as_none() -> None:
    assert artifact_summary.read(_stored({"category": "UNKNOWN"})) is None


FOUR_LINES = {key: ANSWER[key] for key in artifact_summary.TEXT_LINES}


@pytest.mark.parametrize(
    ("answer", "source_type", "complete"),
    [
        (ANSWER, "asx_announcement", True),
        (FOUR_LINES, "asx_announcement", False),
        ({**FOUR_LINES, "confirmed_facts": []}, "asx_announcement", False),
        ({**FOUR_LINES, "confirmed_facts": [], "speculation": []}, "asx_announcement", True),
        (FOUR_LINES, "news", True),
        (FOUR_LINES, "reddit", True),
        ({**ANSWER, "changed": " "}, "asx_announcement", False),
        ({**FOUR_LINES, "matters": None}, "news", False),
    ],
)
def test_a_complete_summary_has_four_lines_and_any_clarity_lists_its_source_needs(
    answer: dict,
    source_type: str,
    complete: bool,
) -> None:
    summary = artifact_summary.from_answer(answer, model=MODEL, prompt_version=PROMPT_VERSION)

    assert artifact_summary.is_complete(summary, source_type=source_type) is complete


def test_no_summary_is_never_complete() -> None:
    assert not artifact_summary.is_complete(None, source_type="news")


@pytest.mark.parametrize(
    ("source_type", "needs_summary"),
    [("asx_announcement", True), ("news", False)],
)
def test_a_legacy_summary_with_only_joined_text_lacks_the_clarity_lists(
    source_type: str,
    needs_summary: bool,
) -> None:
    artifact = _stored(None, "One.\n\nTwo.\n\nThree.\n\nFour.", source_type=source_type)

    assert artifact_summary.needs_summary(artifact) is needs_summary


def test_an_extension_required_for_a_source_type_must_be_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_summary,
        "EXTENSIONS",
        (
            artifact_summary.SummaryExtension(
                "claim_evidence",
                _claim_evidence,
                required_for=frozenset({"asx_announcement"}),
            ),
        ),
    )

    assert not artifact_summary.is_complete(_summary(), source_type="asx_announcement")
    assert artifact_summary.is_complete(
        _summary(claim_evidence=[{"text": "The payment date is 2 January 2040."}]),
        source_type="asx_announcement",
    )
    assert artifact_summary.is_complete(_summary(), source_type="news")


def test_incomplete_announcements_are_the_analysed_ones_with_an_incomplete_summary(
    db_session: Session,
) -> None:
    _ids, before = artifact_summary.incomplete_announcements(db_session, limit=0)

    def analysed(created_day: int, **values) -> Artifact:
        artifact = _new_announcement()
        artifact.analysis_status = AnalysisStatus.COMPLETED
        artifact.created_at = datetime(2000, 1, created_day, tzinfo=timezone.utc)
        for name, value in values.items():
            setattr(artifact, name, value)
        db_session.add(artifact)
        db_session.flush()
        return artifact

    def lines_only(artifact: Artifact) -> None:
        artifact_summary.record(
            db_session,
            artifact,
            artifact_summary.from_answer(FOUR_LINES, model=MODEL, prompt_version=PROMPT_VERSION),
        )

    oldest = analysed(1)
    lines_only(oldest)
    legacy = analysed(2)
    db_session.add(ArtifactSummary(artifact_id=legacy.id, summary_text="A legacy summary."))
    complete = analysed(1)
    artifact_summary.record(db_session, complete, _summary())
    pending = analysed(1, analysis_status=AnalysisStatus.PENDING)
    lines_only(pending)
    news = analysed(1, source_type="news", artifact_type="news_article")
    lines_only(news)
    analysed(1)  # Analysed with no summary row, as when no LLM was switched on.
    db_session.commit()

    first, total = artifact_summary.incomplete_announcements(db_session, limit=1)
    every, _total = artifact_summary.incomplete_announcements(db_session, limit=before + 2)

    assert first == [oldest.id]
    assert total == before + 2
    assert every[:2] == [oldest.id, legacy.id]


def test_the_text_joins_the_lines_it_has_with_blank_lines() -> None:
    summary = Summary(summary="One.", changed="Three.", matters="Four.")

    assert summary.text == "One.\n\nThree.\n\nFour."


@pytest.mark.parametrize(
    ("summary", "brief"),
    [
        (Summary(summary="The summary line.", about="  The   about line. "), "The about line."),
        (Summary(summary="The  summary line.", changed="Changed."), "The summary line."),
        (Summary(changed="Only what changed."), None),
        (None, None),
    ],
)
def test_the_brief_is_about_else_the_summary_line(
    summary: Summary | None,
    brief: str | None,
) -> None:
    assert artifact_summary.brief(summary) == brief


def test_clarity_lists_are_cleaned_and_need_both_lists_to_be_classified() -> None:
    classified = artifact_summary.read(
        _stored(
            {
                "about": "A line.",
                "confirmed_facts": [
                    " Net profit was  $1 billion. ",
                    "Net profit was $1 billion.",
                    None,
                ],
                "speculation": ["Management expects costs to fall."],
            }
        )
    )
    malformed = artifact_summary.read(
        _stored({"about": "A line.", "confirmed_facts": "A malformed legacy value."})
    )

    assert artifact_summary.clarity(classified) == {
        "is_classified": True,
        "confirmed_facts": ["Net profit was $1 billion."],
        "speculation": ["Management expects costs to fall."],
    }
    assert artifact_summary.clarity(malformed) == {
        "is_classified": False,
        "confirmed_facts": [],
        "speculation": [],
    }
    assert artifact_summary.clarity(None)["is_classified"] is False


def test_alert_text_is_the_recorded_summary_text(db_session: Session) -> None:
    recorded = _announcement(db_session)
    artifact_summary.record(db_session, recorded, _summary())
    legacy = _announcement(db_session)
    db_session.add(ArtifactSummary(artifact_id=legacy.id, summary_text="A legacy summary."))
    unsummarised = _announcement(db_session)
    db_session.commit()

    assert artifact_summary.alert_text(db_session, recorded.id) == _summary().text
    assert artifact_summary.alert_text(db_session, legacy.id) == "A legacy summary."
    assert artifact_summary.alert_text(db_session, unsummarised.id) is None
    assert artifact_summary.alert_text(db_session, uuid.uuid4()) is None
