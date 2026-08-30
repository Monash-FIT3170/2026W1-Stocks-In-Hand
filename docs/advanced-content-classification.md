# Advanced Content Classification

Document classification is deterministic, versioned and entirely in process.
Callers use `classify_document(ClassificationInput)` from
`parsing.classification`. The rules engine does not call a database, a network
service, Groq, Gemini or another model.

The score is a deterministic rules score. It is not a probability or a measure
of model certainty.

## Taxonomy

| Stable identifier | Compatibility category |
|---|---|
| `quarterly_trading_update` | `QuarterlyTradingUpdate` |
| `half_year_results` | `HalfYearResults` |
| `full_year_results` | `FullYearResults` |
| `annual_report` | `AnnualReport` |
| `dividend_announcement` | `DividendAnnouncement` |
| `security_notification` | `SecurityNotification` |
| `capital_management` | `CapitalManagement` |
| `corporate_action` | `CorporateAction` |
| `leadership_change` | `LeadershipChange` |
| `guidance_update` | `GuidanceUpdate` |
| `governance_meeting` | `GovernanceMeeting` |
| `regulatory_legal` | `RegulatoryLegal` |
| `executive_transcript` | `ExecutiveTranscript` |

`unknown` is an outcome, not a category. A result is `needs_review` when
evidence conflicts or the top two deterministic scores are within the configured
margin. Both `needs_review` and `unknown` are stored as `UNKNOWN` for legacy
consumers.

## Adding or changing a category

1. Add or update the declarative definition in
   `backend/parsing/classification/taxonomy.py`.
2. Use stable lowercase identifiers and keep the compatibility mapping explicit.
3. Prefer strong title phrases and ASX form identifiers. Add body support,
   negative evidence and whole-token patterns where needed.
4. Add sanitized regression excerpts and manifest entries before changing the
   rules. Each enabled category should retain at least five positive fixtures.
5. Run the focused public-interface tests and evaluator.
6. Add an extractor to `backend/parsing/extractors.py` only if a separate,
   existing metric extractor supports the category. Classification does not
   imply that metric extraction exists.

## Adding a regression fixture

Add a short sanitized text excerpt under
`backend/tests/fixtures/classification/text/`, then add an entry to
`backend/tests/fixtures/classification/manifest.json`. Include a stable fixture
identifier, title, optional filename, text path, expected category and a short
rationale. Use `expected_category: "unknown"` for unsupported or genuinely
ambiguous documents. `acceptable_alternatives` documents the categories involved
in a genuine ambiguity, but a confirmed classification still counts as an
unknown false positive.

Run:

```bash
PYTHONPATH=backend pytest -q backend/tests/test_classification.py
PYTHONPATH=backend python -m tools.evaluate_classification --classifier current
```

## Reclassifying stored artifacts

The command reads only artifacts that already contain raw text and have an older
classifier version. It updates classification metadata in bounded batches. It
does not run discovery, download, summary, sentiment or metric extraction.

Preview one ticker:

```bash
cd backend
python -m tools.reclassify_artifacts \
  --dry-run \
  --ticker CSL \
  --batch-size 100 \
  --limit 1000
```

Apply the same bounded selection only after reviewing the preview:

```bash
cd backend
python -m tools.reclassify_artifacts \
  --apply \
  --ticker CSL \
  --batch-size 100 \
  --limit 1000
```

The JSON summary reports scanned, changed, unchanged, ambiguous, unknown and
failed counts. Repeating the command for `rules-v2` skips already current rows.
Unrelated metadata is preserved. Existing extracted data is retained and marked
stale when its compatibility category changes.
