# Advanced Content Classification Baseline

Recorded on 2026-08-29 from `main` at commit
`dabaaf0e9564debf55291b92407fcc1eb250a42c`, before changing classifier
behaviour.

## Fixture coverage

- Total fixtures: 85
- Supported categories: 13
- Positive fixtures: 65, with 5 per supported category
- Negative, unsupported and ambiguity fixtures: 20
- Sanitized excerpts: 85

## Legacy rules result

| Metric | Result |
|---|---:|
| Macro F1 | 0.4765 |
| Unknown false-positive rate | 15.0% (3 of 20) |
| Ambiguous results | 0 |
| Median fixture classification time | 0.0157 ms |

| Category | Fixtures | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| `annual_report` | 5 | 0.0000 | 0.0000 | 0.0000 |
| `capital_management` | 5 | 0.0000 | 0.0000 | 0.0000 |
| `corporate_action` | 5 | 0.8333 | 1.0000 | 0.9091 |
| `dividend_announcement` | 5 | 0.8000 | 0.8000 | 0.8000 |
| `executive_transcript` | 5 | 1.0000 | 0.8000 | 0.8889 |
| `full_year_results` | 5 | 0.0000 | 0.0000 | 0.0000 |
| `governance_meeting` | 5 | 0.0000 | 0.0000 | 0.0000 |
| `guidance_update` | 5 | 0.0000 | 0.0000 | 0.0000 |
| `half_year_results` | 5 | 0.8333 | 1.0000 | 0.9091 |
| `leadership_change` | 5 | 1.0000 | 0.8000 | 0.8889 |
| `quarterly_trading_update` | 5 | 0.8333 | 1.0000 | 0.9091 |
| `regulatory_legal` | 5 | 0.0000 | 0.0000 | 0.0000 |
| `security_notification` | 5 | 1.0000 | 0.8000 | 0.8889 |

The legacy classifier returned `unknown` for all fixtures in six proposed
categories because those categories did not exist. It also accepted three
genuinely ambiguous fixtures as confirmed classifications and misclassified an
interim dividend as half-year results. Registration-order selection produced no
review state.

Reproduce the baseline from the repository root with:

```bash
PYTHONPATH=backend python -m tools.evaluate_classification --classifier legacy
```
