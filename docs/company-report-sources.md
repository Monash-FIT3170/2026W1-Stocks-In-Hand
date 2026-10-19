# Company report source links

ClickUp task: `86d4a0a1d` — sources specify the exact document on company reports.

A report's original-source link should open the specific stored document when
available. It should not select a generic investor or announcements page ahead
of a known document. Company citations show the report title directly in the
link, including compact brief and claim citations, and retain the supplied date.

## Link selection

`app.services.claim_traceability.artifact_source_url` selects the first usable
HTTP(S) URL in this order:

1. `Artifact.document_url`: the current document link.
2. `Artifact.artifact_metadata.pdf_url`: a document link on legacy records.
3. `Artifact.canonical_url`: the canonical publication page.
4. `Artifact.url`: the legacy original link.
5. `Artifact.artifact_metadata.source_url`: the legacy source/listing page.

Empty, malformed and non-HTTP(S) candidates are skipped. If no candidate is
usable, the API returns a missing link and existing UI unavailable states apply.
No filename, document title, date or URL is invented. Records that only have a
publication or listing URL continue to use that fallback. An adapter's stored
document URL can itself be a specific announcement article that resolves to a
download; this selector does not fetch or resolve URLs.

The selector is shared by market/company feed cards, brief and history source
lists, claim citations and category-sentiment evidence. News and public
discussion use the same rule and retain their canonical article/post links when
they have no document URL. Existing API response shapes are unchanged, and no
database migration or summary regeneration is required.

## Verification

From the repository root:

```sh
.venv/bin/python -m pytest -q backend/tests/test_report_sources.py backend/tests/test_artifact_card.py backend/tests/test_claim_traceability.py
```

These tests cover document preference over generic pages, legacy PDF links,
fallbacks, unsafe URLs, title/date preservation, consistency across cards and
evidence, and non-report publication links.

From `frontend/`:

```sh
npm test
npm run lint
npm run build
```

The source component tests check visible document titles in both compact and full
layouts, supplied dates, legacy title fallbacks and unavailable unsafe links.
