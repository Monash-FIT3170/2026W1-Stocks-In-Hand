"""Validate claim evidence against the stored source document."""

import re
from collections.abc import Mapping
from typing import Any


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
