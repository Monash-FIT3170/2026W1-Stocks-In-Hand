"""Document links remain specific across current and legacy artifact shapes."""

import pytest

from app.models.artifact import Artifact
from app.services.claim_traceability import artifact_source_url


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"document_url": " https://example.test/report.pdf "}, "https://example.test/report.pdf"),
        ({"artifact_metadata": {"pdf_url": "https://example.test/legacy.pdf"}}, "https://example.test/legacy.pdf"),
        ({}, "https://example.test/report"),
        ({"canonical_url": None}, "https://example.test/old-report"),
        ({"canonical_url": None, "url": None}, "https://example.test/announcements"),
        ({"document_url": "javascript:alert(1)", "artifact_metadata": {"pdf_url": "https://[bad"}}, "https://example.test/report"),
        ({"canonical_url": " ", "url": "file:///tmp/report.pdf", "artifact_metadata": None}, None),
        ({"canonical_url": None, "url": None, "artifact_metadata": []}, None),
    ],
)
def test_report_link_prefers_safe_documents_then_publication_pages(values, expected):
    fields = {
        "artifact_type": "asx_announcement_other",
        "source_type": "asx_announcement",
        "canonical_url": "https://example.test/report",
        "url": "https://example.test/old-report",
        "artifact_metadata": {"source_url": "https://example.test/announcements"},
    }
    artifact = Artifact(**{**fields, **values})

    assert artifact_source_url(artifact) == expected


def test_current_document_takes_precedence_over_legacy_pdf_and_listing():
    artifact = Artifact(
        artifact_type="asx_announcement_other",
        document_url="https://example.test/current.pdf",
        canonical_url="https://example.test/report",
        url="https://example.test/announcements",
        artifact_metadata={"pdf_url": "https://example.test/legacy.pdf"},
    )

    assert artifact_source_url(artifact) == "https://example.test/current.pdf"
