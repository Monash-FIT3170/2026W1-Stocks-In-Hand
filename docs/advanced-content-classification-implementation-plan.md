# Advanced Content Classification Implementation Plan

## Baseline

- Branch reviewed: `main`
- Baseline commit: `dabaaf0e9564debf55291b92407fcc1eb250a42c`
- Current implementation:
  - `backend/parsing/classifier.py` chooses one category using keyword scores.
  - `backend/parsing/categories/base.py` combines classification rules and metric extraction in `ReportCategory`.
  - The first non-zero category score is accepted, even when it is below the documented `0.7` threshold.
  - Ties are resolved indirectly by category registration order.
  - Only the winning category and numeric confidence are retained.
  - There is no labelled evaluation set, ambiguity state, explanation, classifier version, or reclassification command.
  - Both the AWS analysis worker and the local parsing pipeline call the same basic classifier.

## Goal

Create a deterministic, explainable and versioned classification module for company reports and ASX announcements. It must classify supported documents consistently, identify ambiguous or unsupported documents honestly, preserve evidence explaining the result, and remain usable by both the AWS worker and local pipeline without network calls.

## Outcomes

1. Every analysed company document receives one of three statuses:
   - `classified`: one category has sufficient evidence and separation from alternatives.
   - `needs_review`: evidence exists, but the leading categories are too close or conflict.
   - `unknown`: no supported category has sufficient evidence.
2. Every result records the classifier version, selected category, score, alternatives and matched evidence.
3. Classification behaviour is deterministic and tested through one small interface.
4. Classification is separated from category-specific metric extraction.
5. Existing consumers continue receiving `category` and `category_confidence` during migration.
6. A labelled fixture set measures classification quality and prevents regressions.
7. Existing artifacts can be reclassified safely and idempotently without re-downloading documents or rerunning sentiment.

## Scope

### In scope

- Company reports and ASX announcements processed by the document analysis pipeline.
- A versioned rules engine using titles, filenames, document text and source metadata.
- Explicit positive rules, negative rules, title patterns and document-form identifiers.
- Ambiguity handling and an honest `unknown` result.
- Top candidate results and human-readable matched evidence.
- A labelled evaluation fixture set and quality report.
- Persistence of structured classification metadata in `Artifact.artifact_metadata`.
- A controlled reclassification command for existing artifacts.
- Compatibility with current ticker, announcement, summary and sentiment consumers.

### Out of scope

- Metric extraction from the selected category. That remains the separate "Better metric extraction" task.
- Claim tracing, direct quotations and structured fact storage.
- Sentiment, risk, theme or narrative generation.
- User-facing review workflows or administration screens.
- Training or hosting a machine-learning model.
- Calling Groq, Gemini or another remote model in the classification path.
- Database schema changes unless JSONB metadata proves insufficient during implementation.

## Proposed taxonomy

Use stable lowercase identifiers internally. Keep the current class-style names only as compatibility values while consumers migrate.

| Identifier | Compatibility value | Intended documents |
|---|---|---|
| `quarterly_trading_update` | `QuarterlyTradingUpdate` | Quarterly operational, production or trading updates |
| `half_year_results` | `HalfYearResults` | Interim results, half-year reports and Appendix 4D packages |
| `full_year_results` | `FullYearResults` | Full-year results and Appendix 4E packages |
| `annual_report` | `AnnualReport` | Annual reports and concise annual reports |
| `dividend_announcement` | `DividendAnnouncement` | Dividend declarations, distributions and Appendix 3A.1 notices |
| `security_notification` | `SecurityNotification` | Appendix 3G, 3H and related security notices |
| `capital_management` | `CapitalManagement` | Capital raisings, buybacks, placements, entitlement offers and share purchase plans |
| `corporate_action` | `CorporateAction` | Acquisitions, disposals, mergers, demergers and joint ventures |
| `leadership_change` | `LeadershipChange` | Executive and board appointments, departures and restructures |
| `guidance_update` | `GuidanceUpdate` | New, changed, reaffirmed or withdrawn guidance |
| `governance_meeting` | `GovernanceMeeting` | AGM notices, meeting results and governance documents |
| `regulatory_legal` | `RegulatoryLegal` | Regulatory decisions, litigation and formal investigations |
| `executive_transcript` | `ExecutiveTranscript` | Executive interviews, briefings and transcripts |

`unknown` is a classification outcome, not a supported document category.

The proposed additions make common ASX document types distinguishable without introducing an unbounded taxonomy. If the team wants a smaller first release, the engine can ship with the existing seven categories while retaining the same interface and metadata contract.

## Module design

### External seam

Create `backend/parsing/classification/` and expose only this interface from its `__init__.py`:

```python
def classify_document(document: ClassificationInput) -> ClassificationResult:
    ...
```

Suggested immutable types:

```python
@dataclass(frozen=True)
class ClassificationInput:
    title: str
    text: str
    filename: str | None = None
    source_type: str | None = None
    source_adapter: str | None = None


@dataclass(frozen=True)
class ClassificationEvidence:
    field: Literal["title", "filename", "text"]
    rule: str
    matched_text: str
    weight: float


@dataclass(frozen=True)
class CategoryCandidate:
    category: str
    score: float
    evidence: tuple[ClassificationEvidence, ...]


@dataclass(frozen=True)
class ClassificationResult:
    status: Literal["classified", "needs_review", "unknown"]
    primary_category: str | None
    compatibility_category: str
    score: float
    candidates: tuple[CategoryCandidate, ...]
    classifier_version: str
```

The caller must not know rule weights, normalization logic, thresholds, category precedence or tie-breaking behaviour. Those belong inside the module implementation.

### Internal implementation

Suggested files:

```text
backend/parsing/classification/
  __init__.py          # exports the one public function and public result types
  engine.py            # scoring, thresholds, ambiguity and result construction
  taxonomy.py          # declarative category definitions and compatibility mapping
  normalization.py     # private text and identifier normalization helpers
  types.py             # immutable input and result types
```

Do not introduce provider ports or adapters. Classification is in-process pure computation and has no external dependency.

### Separation from extraction

Category selection and metric extraction currently meet inside `ReportCategory`. Replace that coupling with two registries behind the parsing implementation:

- Classification taxonomy: determines the document category.
- Extractor registry: maps a classified category identifier to an extractor, where one exists.

`apply_rules()` should first call `classify_document()`. It should call an extractor only when the status is `classified` and an extractor is registered. `needs_review` and `unknown` must produce empty extracted data.

Do not implement missing extractors as part of this feature.

## Classification behaviour

### Normalization

- Normalize Unicode and whitespace.
- Compare case-insensitively while retaining original matched text for evidence.
- Normalize common punctuation variants such as `half-year` and `half year`.
- Treat short patterns such as `1H`, `Q1`, `3G` and `4E` as whole tokens.
- Limit body scanning to a configured maximum number of characters so runtime is bounded.
- Weight title and filename evidence more heavily than body text.

### Rules

Each category definition should declare:

- Strong title phrases.
- Whole-token title patterns.
- Document-form identifiers such as `Appendix 4D`.
- Supporting body phrases.
- Negative or conflicting phrases.
- Optional hard requirements where a category would otherwise be too broad.

Do not rely on category list order for correctness. If a deterministic tie-breaker remains necessary, make it explicit in the engine and include the ambiguity in the result.

### Selection policy

Keep thresholds in one configuration object owned by the module.

- `classified`: top candidate meets the absolute threshold and exceeds the second candidate by the configured margin.
- `needs_review`: at least one candidate meets the evidence threshold, but the result is ambiguous or conflicting.
- `unknown`: no candidate meets the minimum evidence threshold.

The numeric score is a deterministic rules score, not a statistical probability. User-facing copy and internal documentation must not describe it as model certainty.

### Compound documents

Some results packages also announce dividends or guidance. For the first release:

- Select one primary category based on the document's main purpose.
- Retain other supported categories in `candidates`.
- Do not expose multi-label classification as a stable interface yet.

This preserves compatibility while retaining enough information for a future multi-label decision.

## Persistence contract

Store the structured result under `artifact_metadata.classification`:

```json
{
  "classification": {
    "status": "classified",
    "primary_category": "half_year_results",
    "score": 0.91,
    "classifier_version": "rules-v2",
    "candidates": [
      {
        "category": "half_year_results",
        "score": 0.91,
        "evidence": [
          {
            "field": "title",
            "rule": "appendix_4d",
            "matched_text": "Appendix 4D",
            "weight": 6.0
          }
        ]
      }
    ]
  },
  "category": "HalfYearResults",
  "category_confidence": 0.91,
  "classification_method": "rules-v2"
}
```

Compatibility requirements:

- Continue writing `category`, `category_confidence` and `classification_method` until all consumers use the structured object.
- Write `category = "UNKNOWN"` for both `needs_review` and `unknown` so ambiguous documents are not presented as confirmed classifications.
- Preserve unrelated artifact metadata during updates.
- Never erase prior extracted data merely because reclassification is ambiguous. Flag it as stale for later review instead.

## Implementation phases

### Phase 1: Baseline and labelled fixtures

1. Record the current classifier's output for representative existing documents.
2. Add `backend/tests/fixtures/classification/manifest.json` containing:
   - fixture identifier;
   - title and optional filename;
   - source text fixture path;
   - expected category or `unknown`;
   - optional acceptable alternative for genuinely ambiguous documents;
   - short rationale.
3. Include at least five positive fixtures per supported category where source material is available.
4. Include at least 20 negative, unsupported and cross-category ambiguity fixtures.
5. Use short, sanitized excerpts committed to the repository. Do not make tests depend on live websites or external model calls.
6. Add a baseline evaluator that reports category counts, confusion matrix, precision, recall, macro F1, unknown false-positive rate and ambiguous count.

Deliverable: a reproducible baseline report showing current failures before rules are changed.

### Phase 2: Build the classification module

1. Add the immutable input and result types.
2. Move text normalization and scoring behind `classify_document()`.
3. Convert existing category keywords into declarative taxonomy definitions.
4. Add negative rules, explicit thresholds and margin-based ambiguity handling.
5. Preserve deterministic ordering of candidate results.
6. Add focused tests through the external seam, not through private scoring helpers.
7. Keep a temporary wrapper in `backend/parsing/classifier.py` if needed for compatibility, but make it delegate to the new module.

Deliverable: the new module passes the fixture suite without changing production callers.

### Phase 3: Integrate parsing and persistence

1. Update `backend/parsing/analysis.py::apply_rules()` to use `classify_document()`.
2. Pass filename, source type and source adapter when available. Do not make them mandatory for legacy callers.
3. Add an extractor registry keyed by the stable category identifier.
4. Persist structured classification metadata in `backend/lambdas/analysis.py`.
5. Preserve the three flat compatibility fields.
6. Update the local pipeline to use the same interface and output contract.
7. Confirm ticker and announcement routes still render existing category labels.

Deliverable: AWS and local analysis paths produce identical classification results for identical inputs.

### Phase 4: Reclassification and rollout

1. Add a command that selects artifacts with raw text and an older classifier version.
2. Support `--dry-run`, ticker filtering, batch size and maximum row count.
3. Print counts for changed, unchanged, ambiguous, unknown and failed artifacts.
4. Update classification metadata atomically and preserve unrelated metadata.
5. Do not rerun document discovery, download, summary or sentiment.
6. Make repeated execution idempotent for the same classifier version.
7. Run a dry-run in staging and manually review changed high-impact categories before applying updates.

Deliverable: existing documents can adopt the new classifier safely without replaying the ingestion pipeline.

### Phase 5: Observability and documentation

1. Add structured worker log fields for classification status, primary category, score and classifier version.
2. Count `classified`, `needs_review` and `unknown` outcomes by source adapter.
3. Document how to add a category or rule and how to add a regression fixture.
4. Update README text that currently implies all classification is accepted above a simple keyword score.

Deliverable: maintainers can measure classification drift and extend the taxonomy without changing callers.

## Verification plan

### Module tests

- Strong title evidence selects the expected category.
- Body-only evidence requires more support than title evidence.
- Short patterns match whole tokens only.
- Negative rules prevent common false positives.
- A close top-two result becomes `needs_review`.
- No meaningful evidence becomes `unknown`.
- Candidate order and evidence are deterministic.
- Empty, very large and malformed text inputs are handled safely.
- Classification performs no network or database access.

### Integration tests

- `apply_rules()` maps a classified result to the correct compatibility category.
- An ambiguous result does not run a category extractor.
- The analysis worker persists structured and compatibility metadata.
- Existing metadata survives classification updates.
- The local pipeline and worker produce the same result for identical input.
- Existing ticker and announcement route tests continue to pass.

### Evaluation gates

The initial fixture set should meet all of these before rollout:

- Macro F1 of at least `0.85` across categories with five or more fixtures.
- Precision and recall of at least `0.75` for every category with five or more fixtures.
- Unknown false-positive rate no greater than `10%`.
- No regression on high-confidence fixtures for the existing seven categories without an explicit fixture correction.
- Identical results across repeated runs.
- Median classification time below `50 ms` for a 50,000-character input on a development machine.

These gates are initial engineering thresholds, not production claims. Report fixture counts beside every metric so small samples are visible.

### Commands

Use the repository's existing test environment. At minimum, run:

```bash
pytest -q backend/tests/test_classification.py
pytest -q backend/tests/test_document_workers.py
pytest -q backend/tests/test_apis.py
python -m compileall -q backend
git diff --check
```

Also run the repository's complete backend test command before handoff.

## Acceptance criteria

- One `classify_document()` interface owns all classification behaviour.
- The interface returns status, primary category, deterministic score, candidates, evidence and classifier version.
- `needs_review` and `unknown` are distinguishable in structured metadata and both remain `UNKNOWN` to legacy consumers.
- Classification does not depend on registration order, a database, the network or an LLM.
- The AWS worker and local pipeline use the same classification module.
- Metric extraction is invoked only for an unambiguous supported category.
- Structured classification metadata and legacy compatibility fields are persisted together.
- The labelled fixture suite and evaluation gates pass.
- Reclassification supports dry-run, bounded batches and idempotency.
- Existing backend tests pass.
- Documentation explains taxonomy extension, fixture addition and reclassification.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Results packages legitimately match several categories | Keep one primary category, preserve candidates and use a margin-based ambiguity state. |
| Scores are mistaken for probabilities | Name and document them as deterministic rule scores; avoid certainty language. |
| New rules silently change old artifacts | Version results, require fixture evaluation and use dry-run reclassification. |
| Body keywords cause broad false positives | Weight title/form evidence more strongly and support negative rules. |
| Taxonomy expands without enough examples | Require fixtures before enabling a new category. |
| Refactoring breaks downstream labels | Retain compatibility metadata until consumers migrate. |
| Reclassification overwrites other analysis | Merge only the classification keys and update in bounded transactions. |

## Suggested pull request sequence

1. **PR 1: classification fixtures and baseline evaluator**
   - Adds no production behaviour changes.
2. **PR 2: versioned classification module**
   - Adds the deep module, taxonomy and interface-level tests.
3. **PR 3: parsing and worker integration**
   - Replaces callers, persists structured results and keeps compatibility fields.
4. **PR 4: reclassification and observability**
   - Adds the dry-run command, bounded updates, logs and documentation.

Keep each pull request independently testable and avoid combining metric extraction changes with this feature.
