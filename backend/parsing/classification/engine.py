"""Deterministic scoring, thresholds, ambiguity and result construction."""

from __future__ import annotations

from dataclasses import dataclass

from .normalization import find_phrase, safe_text
from .taxonomy import TAXONOMY, CategoryDefinition, PatternRule
from .types import (
    CategoryCandidate,
    ClassificationEvidence,
    ClassificationInput,
    ClassificationResult,
    EvidenceField,
)


CLASSIFIER_VERSION = "rules-v2"


@dataclass(frozen=True)
# pylint: disable-next=too-many-instance-attributes
class _ClassificationConfig:
    body_character_limit: int = 50_000
    score_denominator: float = 10.0
    classified_threshold: float = 0.65
    evidence_threshold: float = 0.25
    ambiguity_margin: float = 0.15
    title_weight: float = 7.0
    filename_weight: float = 6.0
    title_token_weight: float = 6.0
    filename_token_weight: float = 5.0
    form_title_weight: float = 9.0
    form_filename_weight: float = 8.0
    form_body_weight: float = 6.0
    body_weight: float = 2.0
    negative_title_weight: float = -6.0
    negative_filename_weight: float = -5.0
    negative_body_weight: float = -3.0


_CONFIG = _ClassificationConfig()
_SUPPORTED_SOURCE_TYPES = frozenset(
    {"", "announcement", "asx_announcement", "company_report"}
)
_FIELD_ORDER = {
    "title": 0,
    "filename": 1,
    "source_type": 2,
    "source_adapter": 3,
    "text": 4,
}


def _match_rules(
    source: str,
    field: EvidenceField,
    rules: tuple[PatternRule, ...],
    weight: float,
) -> list[ClassificationEvidence]:
    evidence: list[ClassificationEvidence] = []
    for rule in rules:
        matched = find_phrase(
            source,
            rule.pattern,
            token=rule.token,
            regex=rule.regex,
        )
        if matched is not None:
            evidence.append(
                ClassificationEvidence(
                    field=field,
                    rule=rule.name,
                    matched_text=matched,
                    weight=weight,
                )
            )
    return evidence


def _category_candidate(
    category: CategoryDefinition,
    fields: dict[EvidenceField, str],
) -> CategoryCandidate | None:
    evidence: list[ClassificationEvidence] = []
    evidence.extend(
        _match_rules(
            fields["title"], "title", category.title_phrases, _CONFIG.title_weight
        )
    )
    evidence.extend(
        _match_rules(
            fields["filename"],
            "filename",
            category.title_phrases,
            _CONFIG.filename_weight,
        )
    )
    evidence.extend(
        _match_rules(
            fields["title"],
            "title",
            category.title_tokens,
            _CONFIG.title_token_weight,
        )
    )
    evidence.extend(
        _match_rules(
            fields["filename"],
            "filename",
            category.title_tokens,
            _CONFIG.filename_token_weight,
        )
    )
    for field, weight in (
        ("title", _CONFIG.form_title_weight),
        ("filename", _CONFIG.form_filename_weight),
        ("text", _CONFIG.form_body_weight),
    ):
        evidence.extend(
            _match_rules(
                fields[field], field, category.form_identifiers, weight  # type: ignore[arg-type]
            )
        )
    evidence.extend(
        _match_rules(
            fields["text"], "text", category.body_phrases, _CONFIG.body_weight
        )
    )
    for field, weight in (
        ("title", _CONFIG.negative_title_weight),
        ("filename", _CONFIG.negative_filename_weight),
        ("text", _CONFIG.negative_body_weight),
    ):
        evidence.extend(
            _match_rules(
                fields[field], field, category.negative_phrases, weight  # type: ignore[arg-type]
            )
        )

    if not any(item.weight > 0 for item in evidence):
        return None
    evidence.sort(
        key=lambda item: (
            _FIELD_ORDER[item.field],
            -abs(item.weight),
            item.rule,
            item.matched_text.casefold(),
        )
    )
    raw_score = sum(item.weight for item in evidence)
    score = round(max(0.0, min(1.0, raw_score / _CONFIG.score_denominator)), 4)
    return CategoryCandidate(category.identifier, score, tuple(evidence))


def classify_document(document: ClassificationInput) -> ClassificationResult:
    """Classify one document deterministically with no external dependencies."""
    fields: dict[EvidenceField, str] = {
        "title": safe_text(document.title),
        "filename": safe_text(document.filename),
        "text": safe_text(document.text, limit=_CONFIG.body_character_limit),
        "source_type": safe_text(document.source_type),
        "source_adapter": safe_text(document.source_adapter),
    }
    if fields["source_type"].casefold() not in _SUPPORTED_SOURCE_TYPES:
        return ClassificationResult(
            status="unknown",
            primary_category=None,
            compatibility_category="UNKNOWN",
            score=0.0,
            candidates=(),
            classifier_version=CLASSIFIER_VERSION,
        )
    candidates = tuple(
        sorted(
            (
                candidate
                for category in TAXONOMY
                if (candidate := _category_candidate(category, fields)) is not None
            ),
            key=lambda candidate: (-candidate.score, candidate.category),
        )
    )
    if not candidates or candidates[0].score < _CONFIG.evidence_threshold:
        return ClassificationResult(
            status="unknown",
            primary_category=None,
            compatibility_category="UNKNOWN",
            score=candidates[0].score if candidates else 0.0,
            candidates=candidates,
            classifier_version=CLASSIFIER_VERSION,
        )

    top = candidates[0]
    second_score = candidates[1].score if len(candidates) > 1 else 0.0
    has_conflict = any(item.weight < 0 for item in top.evidence)
    category = next(item for item in TAXONOMY if item.identifier == top.category)
    if (
        top.score >= _CONFIG.classified_threshold
        and top.score - second_score >= _CONFIG.ambiguity_margin
        and not has_conflict
    ):
        status = "classified"
        compatibility_category = category.compatibility_category
    else:
        status = "needs_review"
        compatibility_category = "UNKNOWN"
    return ClassificationResult(
        status=status,
        primary_category=top.category,
        compatibility_category=compatibility_category,
        score=top.score,
        candidates=candidates,
        classifier_version=CLASSIFIER_VERSION,
    )
