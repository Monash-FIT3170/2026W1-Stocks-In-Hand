"""Public claim tracing contract; source URLs are derived from persisted artifacts."""

from typing import Literal

from pydantic import BaseModel


class ClaimEvidence(BaseModel):
    field: str
    index: int
    claim_text: str
    quote: str
    start_char: int
    end_char: int
    source_text_sha256: str


class ClaimSource(BaseModel):
    artifact_id: str
    title: str | None
    url: str | None
    published_at: str | None


class TracedClaim(BaseModel):
    id: str
    field: str
    index: int
    text: str
    status: Literal["quoted", "quotation_unavailable", "source_unavailable"]
    source: ClaimSource
    evidence: list[ClaimEvidence]
