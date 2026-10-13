"""Artifact summary: what an artifact says, in six plain-language fields.

A summary has four text lines (``summary``, ``about``, ``changed`` and
``matters``) and two clarity lists (``confirmed_facts`` and ``speculation``)
that only announcement summaries sort their claims into. It is stored twice:
as top-level keys of ``artifacts.artifact_metadata``, which the category
sentiment keyword search still reads, and as the lines joined into the
artifact's one ``artifact_summaries`` row. This module is the only code that
writes either store. ``record`` replaces both inside the caller's
transaction, and ``read`` gives them back as one ``Summary``, recovering
older records that kept only the joined text.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, ColumnElement, Text, case, cast, func, literal, update
from sqlalchemy.dialects.postgresql import JSONB, array, insert
from sqlalchemy.orm import Session, selectinload

from app.models.artifact import Artifact
from app.models.artifact_summary import ArtifactSummary
from app.services.generation import SUMMARY_LIST_KEYS, SUMMARY_TEXT_KEYS, Generated

TEXT_LINES = SUMMARY_TEXT_KEYS
CLARITY_LISTS = SUMMARY_LIST_KEYS

_PARAGRAPH_BREAK = re.compile(r"\r?\n\r?\n")


class EmptySummary(ValueError):
    """A summary with no text line. It is never recorded."""


@dataclass(frozen=True)
class SummaryExtension:
    """A field added to every summary, such as the evidence for each claim.

    ``normalise`` turns a generated answer or stored metadata into the value
    to keep, or None when there is none. The value is stored at the top level
    of ``artifact_metadata`` under ``key``. A summary of a source type in
    ``required_for`` is incomplete without it.
    """

    key: str
    normalise: Callable[[Mapping[str, Any]], Any | None]
    required_for: frozenset[str] = frozenset()


EXTENSIONS: tuple[SummaryExtension, ...] = ()


@dataclass(frozen=True)
class Summary:
    """One artifact's summary, its lines and lists already cleaned.

    A clarity list is None when the summary was never sorted into clarity
    lists, which is different from an empty list.
    """

    summary: str | None = None
    about: str | None = None
    changed: str | None = None
    matters: str | None = None
    confirmed_facts: tuple[str, ...] | None = None
    speculation: tuple[str, ...] | None = None
    model: str | None = None
    prompt_version: str | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    @property
    def lines(self) -> dict[str, str]:
        """The text lines it has, in order."""
        lines = {key: getattr(self, key) for key in TEXT_LINES}
        return {key: line for key, line in lines.items() if line}

    @property
    def text(self) -> str:
        """The lines joined by blank lines, as stored in ``summary_text``."""
        return "\n\n".join(self.lines.values())

    @property
    def is_classified(self) -> bool:
        """Whether its claims were sorted into both clarity lists."""
        return self.confirmed_facts is not None and self.speculation is not None


@dataclass(frozen=True)
class RecordedSummary:
    summary_id: UUID
    summary: Summary


def from_answer(
    answer: Mapping[str, object],
    *,
    model: str | None,
    prompt_version: str | None,
) -> Summary:
    """The summary in a generated answer or in stored metadata, cleaned.

    A line is stripped, and missing when it is empty or not text. A clarity
    list counts only when it is a list: items that are not text or are empty
    are skipped, whitespace is collapsed and repeats are dropped. Each
    extension goes through its own ``normalise``, and other keys are ignored.
    """
    return Summary(
        **{key: _line(answer.get(key)) for key in TEXT_LINES},
        **{key: _items(answer.get(key)) for key in CLARITY_LISTS},
        model=model,
        prompt_version=prompt_version,
        extensions=_extensions(answer),
    )


def from_generated(generated: Generated[dict[str, object]]) -> Summary:
    """The summary in a generated answer, with the model and prompt version that wrote it."""
    return from_answer(
        generated.value,
        model=generated.model,
        prompt_version=generated.prompt_version,
    )


def record(db: Session, artifact: Artifact, summary: Summary) -> RecordedSummary:
    """Replace the artifact's summary inside the caller's transaction.

    Raises ``EmptySummary`` when the summary has no text line. A line, list
    or extension the new summary lacks is removed, and the artifact's other
    metadata, including the caller's unflushed changes, is kept. The artifact
    row stays locked until the caller commits, so a concurrent recorder waits
    instead of overwriting this one. Never commits or rolls back.
    """
    if not summary.lines:
        raise EmptySummary(f"The summary of artifact {artifact.id} has no text")
    db.flush()
    # Every recorder locks the artifact row before the summary row, so two
    # recorders cannot deadlock.
    db.execute(
        update(Artifact)
        .where(Artifact.id == artifact.id)
        .values(artifact_metadata=_metadata_with(summary))
        .execution_options(synchronize_session=False)
    )
    upsert = insert(ArtifactSummary).values(
        id=uuid4(),
        artifact_id=artifact.id,
        summary_text=summary.text,
        model_used=summary.model,
        prompt_version=summary.prompt_version,
    )
    row = db.execute(
        upsert.on_conflict_do_update(
            index_elements=[ArtifactSummary.artifact_id],
            set_={
                "summary_text": upsert.excluded.summary_text,
                "model_used": upsert.excluded.model_used,
                "prompt_version": upsert.excluded.prompt_version,
            },
        ).returning(ArtifactSummary),
        execution_options={"populate_existing": True},
    ).scalar_one()
    db.expire(artifact, ["artifact_metadata", "updated_at", "summaries"])
    return RecordedSummary(summary_id=row.id, summary=summary)


def read(artifact: Artifact) -> Summary | None:
    """The artifact's summary, or None when it has none.

    Lines, lists and extensions come from ``artifact_metadata``, and the
    model and prompt version from the summary row. Older records kept only
    the row's joined text: missing lines are filled from it when it splits
    into exactly four paragraphs, and otherwise text with no line beside it
    becomes the summary line. Reads ``artifact.summaries``, so load a list
    of artifacts with ``WITH_SUMMARY``.
    """
    metadata = artifact.artifact_metadata
    row = artifact.summaries[0] if artifact.summaries else None
    summary = from_answer(
        metadata if isinstance(metadata, Mapping) else {},
        model=row.model_used if row else None,
        prompt_version=row.prompt_version if row else None,
    )
    stored_text = row.summary_text.strip() if row and isinstance(row.summary_text, str) else ""
    lines = {**_paragraph_lines(stored_text), **summary.lines}
    if not lines and stored_text:
        lines = {"summary": stored_text}
    return replace(summary, **lines) if lines else None


# Loads the summary rows of a list of artifacts in one more query, so ``read``
# does not query once per artifact.
WITH_SUMMARY = selectinload(Artifact.summaries)


def _line(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _items(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    items: list[str] = []
    for item in value:
        cleaned = " ".join(item.split()) if isinstance(item, str) else ""
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return tuple(items)


def _extensions(values: Mapping[str, object]) -> dict[str, Any]:
    normalised = {extension.key: extension.normalise(values) for extension in EXTENSIONS}
    return {key: value for key, value in normalised.items() if value is not None}


def _metadata_with(summary: Summary) -> ColumnElement[Any]:
    """``artifact_metadata`` with every summary key replaced by this summary's."""
    extension_keys = tuple(extension.key for extension in EXTENSIONS)
    stored: dict[str, Any] = dict(summary.lines)
    for key in CLARITY_LISTS:
        items = getattr(summary, key)
        if items is not None:
            stored[key] = list(items)
    for key in extension_keys:
        if key in summary.extensions:
            stored[key] = summary.extensions[key]
    # Metadata set to None is stored as a JSON null, which is not an object.
    current = case(
        (func.jsonb_typeof(Artifact.artifact_metadata) == "object", Artifact.artifact_metadata),
        else_=literal({}, JSONB),
    )
    return current.op("-")(
        cast(array((*TEXT_LINES, *CLARITY_LISTS, *extension_keys)), ARRAY(Text))
    ).op("||")(literal(stored, JSONB))


def _paragraph_lines(text: str) -> dict[str, str]:
    """The four lines of joined text, when it splits into exactly four paragraphs."""
    paragraphs = [paragraph.strip() for paragraph in _PARAGRAPH_BREAK.split(text)]
    if len(paragraphs) != len(TEXT_LINES) or not all(paragraphs):
        return {}
    return dict(zip(TEXT_LINES, paragraphs, strict=True))
