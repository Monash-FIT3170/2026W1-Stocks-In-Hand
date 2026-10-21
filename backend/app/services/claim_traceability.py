"""Validate claim evidence against the stored source document."""

from __future__ import annotations

import re
from urllib.parse import urlparse
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.services.artifact_summary import Summary


CLAIM_KINDS = {"confirmed_fact": "confirmed_facts", "speculation": "speculation"}


def exact_source_passage(raw_text: object, passage: object) -> str | None:
    """Return the source wording when a passage matches after whitespace cleanup."""
    if not isinstance(raw_text, str) or not isinstance(passage, str):
        return None
    document = " ".join(raw_text.split())
    cleaned = " ".join(passage.split())
    if not cleaned:
        return None
    match = re.search(re.escape(cleaned), document, flags=re.IGNORECASE)
    return match.group(0) if match else None


def normalise_claim_evidence(summary: Mapping[str, Any]) -> list[dict[str, str]]:
    """Keep one well-formed evidence record per classified claim."""
    records = summary.get("claim_evidence")
    if not isinstance(records, list):
        return []
    evidence = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        text, kind, passage = (record.get(key) for key in ("text", "kind", "passage"))
        if (
            not isinstance(text, str)
            or not isinstance(kind, str)
            or not isinstance(passage, str)
        ):
            continue
        if not all(value.strip() for value in (text, kind, passage)):
            continue
        text = " ".join(text.split())
        claim_key = CLAIM_KINDS.get(kind)
        claims = summary.get(claim_key) if claim_key else None
        if not isinstance(claims, list) or text not in {
            " ".join(claim.split()) for claim in claims if isinstance(claim, str)
        }:
            continue
        key = (kind, text)
        if key not in seen:
            evidence.append({
                "text": text,
                "kind": kind,
                "passage": " ".join(passage.split()),
            })
            seen.add(key)
    return evidence


def validated_claim_evidence(
    summary: Mapping[str, Any],
    raw_text: object,
) -> list[dict[str, str]]:
    """Discard invented quotations and retain the document's original wording."""
    evidence = []
    for record in normalise_claim_evidence(summary):
        passage = exact_source_passage(raw_text, record["passage"])
        if passage:
            evidence.append({**record, "passage": passage})
    return evidence


def safe_source_url(value: object) -> str | None:
    """Return a usable web source URL, rejecting malformed or unsafe schemes."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.hostname else None
    except ValueError:
        return None


def traceable_claims(artifact: Artifact | None, summary: Summary | None) -> list[dict[str, Any]]:
    """Attach verified quotations and original publication dates to summary claims."""
    if artifact is None or summary is None:
        return []
    claims = {
        "confirmed_facts": list(summary.confirmed_facts or ()),
        "speculation": list(summary.speculation or ()),
        "claim_evidence": summary.extensions.get("claim_evidence", []),
    }
    evidence = {
        (record["kind"], record["text"]): record["passage"]
        for record in validated_claim_evidence(claims, artifact.raw_text)
    }
    url = artifact_source_url(artifact)
    result = []
    for kind, key in CLAIM_KINDS.items():
        for claim in claims[key]:
            passage = evidence.get((kind, claim)) or exact_source_passage(artifact.raw_text, claim)
            source = {
                "label": (artifact.source_type or "Source").replace("_", " ").title(),
                "title": artifact.title or "Source",
                "url": url,
                "published_at": artifact.published_at.isoformat() if artifact.published_at else None,
                "evidence_text": passage,
            } if url else None
            result.append({"text": claim, "kind": kind, "source": source})
    return result


def artifact_source_url(artifact: Artifact) -> str | None:
    """Prefer the direct document, then the canonical and legacy source links."""
    return next(
        (url for value in (artifact.document_url, artifact.canonical_url, artifact.url)
         if (url := safe_source_url(value))),
        None,
    )
