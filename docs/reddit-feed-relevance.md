# Reddit feed relevance

Reddit posts need a recorded company association, completed analysis and an explicit
`feed_eligible: true` before appearing in the market feed or being selected for a
ticker discussion digest. General advice and portfolio reviews are assessed before
summarisation. An unmatched post is rejected without an LLM call, including when
older metadata contains an approval. Direct re-summarisation uses the same check.

Official filings and the existing publisher-news compatibility policy are unchanged.
No schema migration is required. Old Reddit records without decisions become hidden
until reassessed; existing summaries are retained for audit and source inspection.

## Legacy records

Use a disposable local/staging database first. From `backend/`:

```bash
python -m tools.reassess_reddit_feed --dry-run --limit 50
python -m tools.reassess_reddit_feed --dry-run --ticker BHP --limit 20
python -m tools.reassess_reddit_feed --apply --limit 20
```

Dry-run is the default. It lists IDs, titles and original links, makes no LLM calls,
and performs no writes. Applying makes at most one eligibility call per matched
post, capped at 200 records; unmatched posts are rejected without generation.
Configure the existing LLM provider before applying. Failed assessments retain their
previous decision and are reported with a nonzero command exit status. Review the
results before applying another batch. `--include-decided` explicitly includes
previous approvals/rejections for reassessment under the updated prompt.

Only eligibility metadata changes. Original URLs, ticker links, post content,
summaries, sentiment, and analysis status remain intact. Concurrent changes to the
eligibility decision are skipped. No production reassessment has been performed
as part of implementing this tool; agree a production run with the team.

## Verification

- Test the reported titles "Income etfs" and "Am i in the right direction at
  19 years old?", a portfolio post mentioning BHP, and substantive BHP research.
- New general-advice posts must be rejected before summary generation. Ticker
  mentions alone must not qualify a post; useful critical company research can.
- Confirm only approved, company-linked posts appear in the default feed and
  discussion digest. Follow retained posts' original Reddit links and inspect
  company/source attribution.
- Preview old undecided records, apply a small batch in staging, and verify the
  decisions in the feed. A failed LLM call must not overwrite a saved decision.
- Run `python -m pytest tests/test_reddit_relevance.py tests/test_generation.py
  tests/test_artifact_analysis.py tests/test_announcements.py` from `backend/`.
  The database suites require a disposable migrated Postgres instance.
