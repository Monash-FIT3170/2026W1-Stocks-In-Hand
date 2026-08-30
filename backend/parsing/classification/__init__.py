"""Deterministic document classification through one public interface."""

from .engine import classify_document
from .types import (
    CategoryCandidate,
    ClassificationEvidence,
    ClassificationInput,
    ClassificationResult,
)

__all__ = [
    "CategoryCandidate",
    "ClassificationEvidence",
    "ClassificationInput",
    "ClassificationResult",
    "classify_document",
]
