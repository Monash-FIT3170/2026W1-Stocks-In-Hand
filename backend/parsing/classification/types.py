"""Immutable public input, evidence, candidate and result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


EvidenceField = Literal[
    "title", "filename", "text", "source_type", "source_adapter"
]
ClassificationStatus = Literal["classified", "needs_review", "unknown"]


@dataclass(frozen=True)
class ClassificationInput:
    """Document fields available to the deterministic rules engine."""
    title: str
    text: str
    filename: str | None = None
    source_type: str | None = None
    source_adapter: str | None = None


@dataclass(frozen=True)
class ClassificationEvidence:
    """One matched positive or negative rule with its original text."""
    field: EvidenceField
    rule: str
    matched_text: str
    weight: float


@dataclass(frozen=True)
class CategoryCandidate:
    """A scored category and the ordered evidence that produced its score."""
    category: str
    score: float
    evidence: tuple[ClassificationEvidence, ...]


@dataclass(frozen=True)
class ClassificationResult:
    """The complete versioned classification decision."""
    status: ClassificationStatus
    primary_category: str | None
    compatibility_category: str
    score: float
    candidates: tuple[CategoryCandidate, ...]
    classifier_version: str
