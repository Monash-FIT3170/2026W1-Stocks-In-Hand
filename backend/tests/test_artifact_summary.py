"""The artifact summary module, recording and reading summaries on Postgres.

``record`` replaces both stores of a summary, the top-level metadata keys and
the artifact's one ``artifact_summaries`` row, inside the caller's
transaction. ``read`` gives the summary back, recovering older records that
kept only the joined text.
"""

import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.models.artifact import Artifact
from app.models.artifact_summary import ArtifactSummary
from app.services import artifact_summary
from app.services.artifact_summary import EmptySummary, Summary

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
    session = sessionmaker(bind=connection)()
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


def _stored(metadata: dict | None = None, summary_text: str | None = None) -> Artifact:
    """An unsaved artifact holding a summary the way older code stored it."""
    artifact = Artifact(artifact_type="asx_announcement_other", artifact_metadata=metadata)
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


def test_a_registered_extension_round_trips_and_other_keys_are_dropped(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def claim_evidence(values):
        evidence = values.get("claim_evidence")
        return evidence if isinstance(evidence, list) else None

    monkeypatch.setattr(
        artifact_summary,
        "EXTENSIONS",
        (artifact_summary.SummaryExtension("claim_evidence", claim_evidence),),
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
