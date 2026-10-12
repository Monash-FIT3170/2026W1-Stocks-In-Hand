# Advanced claim traceability

ClickUp story: `86d48cxxz` — every claim should be traceable to its source so users can verify information.

## Behaviour

Generated artifact summaries request supporting direct quotations from the source text. Each factual or speculative list item has its own claim reference. The `summary`, `about`, `changed`, and `matters` text fields also receive evidence references. News and individual public discussion summaries use the same evidence format.

The ticker summary, announcement cards (market and ticker feeds), deep-dive timeline, and category signal cards let users expand quotations and open the original source. Forecasts retain their speculation label even when the source explicitly states them. Quotations are rendered as escaped text, with original line breaks preserved.

A source link alone does not count as a matched quotation. Claims without usable evidence show an explicit missing quotation message; claims without an HTTP(S) source link show a missing source message. Older summaries remain readable without manufacturing evidence.

## Evidence and provenance

`artifact_metadata.claim_evidence` stores an array of:

```json
{
  "field": "confirmed_facts",
  "index": 0,
  "claim_text": "Revenue rose by 12%.",
  "quote": "Revenue increased by 12% in the half year.",
  "start_char": 140,
  "end_char": 183,
  "source_text_sha256": "<SHA-256 of the complete stored raw text>"
}
```

Indexes are zero-based, and text fields use index `0`. Character offsets identify a Python Unicode string slice (`raw_text[start_char:end_char]`), with an exclusive end. They refer to extracted text, not positions in HTML or bytes in a PDF. Page numbers are not inferred from text offsets.

Quotation matching accepts whitespace differences from PDF line wrapping. Numbers, wording, case and punctuation must match. Quotes are restricted to 12–1200 characters; at most 64 proposed evidence entries are processed per artifact. Duplicates and invalid field/index references are discarded. Blank clarity items are removed with their evidence indexes remapped to preserve the original association.

A quotation match establishes fidelity to the stored text. It does not establish that the publisher's statement is true or that the passage logically supports the generated interpretation. The UI tells users to review the source in context. OCR may affect the quality of the stored text.

At read time, quotations are checked again against the current claim wording and complete source text fingerprint. A changed claim or changed source text invalidates previous evidence. Source title, artifact ID and publication date come from the artifact; the URL prefers `document_url`, then legacy `pdf_url`, then `url`. Model-supplied URLs are discarded. Only absolute HTTP(S) links without credentials are exposed. Reading evidence never downloads a user-supplied URL or invokes the model.

## API

`GET /artifacts/{artifact_id}/claims` returns typed claim records. Unknown artifacts return `404`; an existing artifact without structured claims returns `[]`.

The ticker brief/overview, ticker news feed, deep-dive timeline market announcement feed, and category signals include the same `claims` records:

- `id`, `field`, `index`, `text` identify the generated claim.
- `status` is `quoted`, `quotation_unavailable` or `source_unavailable`.
- `source` contains `artifact_id`, `title`, `url`, and `published_at`.
- `evidence` contains the matched quotation records.

Existing fields remain available. Category signals expose constituent artifact claims with their own source evidence; aggregate sentiment metrics retain their model provenance. Quotations belong to individual source claims, rather than implying that one quotation supports the entire aggregate. Standalone generated discussion digests do not acquire a source quotation from a single post.

## Existing records and regeneration

No database migration is required: evidence is stored in the existing JSON metadata column. New summaries persist evidence through the queued analysis worker, manual summary API and local parsing path. New summaries clear previous evidence when the model omits it. Prompt provenance versions are `llm-announcement-summary-v4`, `llm-news-summary-v3` and `llm-public-discussion-summary-v3`.

For an existing artifact, an administrator can use `POST /gemini/summarise/artifact/{artifact_id}` to regenerate its summary and evidence with the configured LLM. Despite the legacy route name, it uses the configured provider. Ticker-wide summary backfill revisits summaries without a `claim_evidence` array. A regenerated summary can still have missing quotations if none passed validation. Regeneration changes summary wording and may invoke a paid provider; no production backfill is performed automatically.

## Verification

```bash
PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
cd frontend
npm test
npm run lint
npm run build
```

Backend tests cover quote fidelity, whitespace, fabricated excerpts, stale evidence, duplicate passages, invalid indexes, unsafe URLs, storage normalization, and public API serialization. Component tests cover escaped quotations, missing evidence, factual/speculative separation, and mismatched displayed wording.

For a manual check, regenerate one artifact, open its ticker summary, expand a quotation below a reported fact and one below a forecast, and open their original document links. Check ticker news and market announcement cards, then the deep-dive “Trace individual claims” panel. Repeat at a narrow mobile width. Use an older artifact to confirm missing evidence is labelled clearly.

## Groq JSON-mode errors

A Groq `400 json_validate_failed` response means JSON-mode validation rejected the generated output; a successful short connectivity test does not rule this out. After that specific error, the application retries once without provider JSON mode, keeping the same prompt. The normal JSON parser, schema validation and bounded repair still apply. If a subsequent rejection includes a non-empty `failed_generation` string, it is processed as untrusted model output. Quotations still have to match the stored source text after repair. Other HTTP errors retain their failure status, and provider error bodies are not exposed to users. A generation that cannot be repaired still fails instead of being saved as a valid summary.

Summary display fields (`summary`, `about`, `changed`, `matters`) must be non-empty strings. Repair requests include bounded original source context so unusable output can be regenerated from evidence rather than replaced with blank fields. Empty or unrecoverable summaries fail validation before persistence instead of returning a misleading successful result. Source context and malformed output are JSON-encoded and bounded together below the default Bedrock prompt cap.

Groq summary requests for `openai/gpt-oss-20b` and `openai/gpt-oss-120b` use strict JSON Schema output, requiring typed summary fields and a quotation array. News/discussion schemas omit the official-announcement clarity lists. Other Groq models retain JSON Object Mode; Bedrock request formatting is unchanged. See [Groq structured output documentation](https://console.groq.com/docs/structured-outputs). Strict schema compliance does not establish quotation fidelity or claim truth: the application still validates both field content and source-text matches.

Structured GPT-OSS summary requests use temperature zero and low reasoning effort, exclude reasoning from returned responses, and cap completion tokens at 4096. A live synthetic director-notice check with these settings produced non-empty summary fields and exact source quotations. These settings do not replace source verification or the empty-summary rejection.
