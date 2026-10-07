"""Each category definition owns every fact about its category.

Adding a category used to mean editing seven places: the taxonomy, the
extractor registry, the categories list, the storage artifact_type map, the
evaluator's name map, the ArtifactType enum and the sentiment keywords.
"""

from __future__ import annotations

from app.schemas.artifact import ArtifactType
from app.sentiment_buckets import SENTIMENT_BUCKETS
from parsing.classification.taxonomy import (
    OTHER_ARTIFACT_TYPE,
    TAXONOMY,
    artifact_type_for,
    category_definition,
)

# Stored in artifacts.artifact_metadata["category"] and artifacts.artifact_type.
# These values must not change.
STORED_CATEGORY_NAMES = {
    "quarterly_trading_update": "QuarterlyTradingUpdate",
    "dividend_announcement": "DividendAnnouncement",
    "guidance_update": "GuidanceUpdate",
    "half_year_results": "HalfYearResults",
    "full_year_results": "FullYearResults",
    "annual_report": "AnnualReport",
    "security_notification": "SecurityNotification",
    "capital_management": "CapitalManagement",
    "corporate_action": "CorporateAction",
    "leadership_change": "LeadershipChange",
    "governance_meeting": "GovernanceMeeting",
    "regulatory_legal": "RegulatoryLegal",
    "executive_transcript": "ExecutiveTranscript",
}
STORED_ARTIFACT_TYPES = {
    "DividendAnnouncement": "dividend_announcement",
    "SecurityNotification": "security_notification",
    "LeadershipChange": "leadership_change",
}


def test_every_definition_is_complete() -> None:
    artifact_types = {member.value for member in ArtifactType}

    for definition in TAXONOMY:
        assert definition.label.strip(), definition.identifier
        assert definition.artifact_type in artifact_types, definition.identifier
        assert definition.sentiment_bucket in (*SENTIMENT_BUCKETS, None), definition.identifier
        assert definition.title_phrases or definition.form_identifiers, definition.identifier

    for field in ("identifier", "compatibility_category", "label"):
        values = [getattr(definition, field) for definition in TAXONOMY]
        assert len(values) == len(set(values)), field


def test_stored_category_names_do_not_change() -> None:
    assert {
        definition.identifier: definition.compatibility_category for definition in TAXONOMY
    } == STORED_CATEGORY_NAMES


def test_stored_artifact_types_do_not_change() -> None:
    for name in [*STORED_CATEGORY_NAMES.values(), "UNKNOWN"]:
        assert artifact_type_for(name) == STORED_ARTIFACT_TYPES.get(name, OTHER_ARTIFACT_TYPE)


def test_only_categories_with_metrics_have_an_extractor() -> None:
    with_extractor = {
        definition.identifier for definition in TAXONOMY if definition.extractor is not None
    }

    assert with_extractor == {
        "dividend_announcement",
        "security_notification",
        "leadership_change",
    }
    dividend = category_definition("dividend_announcement")
    assert dividend.extractor.extract(
        "Interim Dividend",
        "The board declared an interim dividend of 18 cents per share.",
    )["amount_per_share"] == "18 cents"


def test_a_missing_or_unknown_category_has_no_definition() -> None:
    assert category_definition(None) is None
    assert category_definition("not_a_category") is None
