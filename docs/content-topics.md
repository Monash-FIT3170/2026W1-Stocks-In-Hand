# Content Topics

Automated content classification: LLM-assisted topic detection and clustering
for the themes the project specification names. Every analysed artifact
(announcement, news story or public discussion post) is tagged with the
content topics it discusses, and one ticker's artifacts about one development
are grouped into topic clusters.

A content topic is not a classification category. A category is the one kind
of document an announcement is, decided by the deterministic `rules-v2`
classifier (see [advanced content classification](advanced-content-classification.md)).
A content topic is what any artifact is about, and an artifact may have
several. Nor is it a sentiment bucket.

## Topics

| Identifier | Label | Covers |
|---|---|---|
| `earnings_guidance` | Earnings and guidance | Results, profit, revenue, margins, and guidance given, confirmed, upgraded or downgraded |
| `litigation` | Litigation | Class actions, lawsuits, judgments, appeals, injunctions and legal settlements |
| `regulation` | Regulation | Regulators (ASIC, ACCC, APRA, AUSTRAC and others), approvals, penalties, legislation, royalties |
| `product_launch` | Product launches | New products, services and projects launched, released or brought into first production |
| `macro_exposure` | Macro-economic exposure | Interest rates, inflation, exchange rates, commodity prices, demand, tariffs, sanctions, conflict |

The identifiers live in `backend/app/content_topic_vocabulary.py` (stored
values, CHECK constraints) and `backend/parsing/content_topics/taxonomy.py`
(labels, descriptions, rules). A test holds the two lists equal, and the
frontend copy is `frontend/src/app/lib/contentTopics.js`.

## How an artifact's topics are decided

`app.services.content_topics.decide_topics` is the one place:

1. The rules in `parsing.content_topics.detect_topics` always run. They read
   the title and the first 12,000 characters of text. A topic phrase in the
   title scores 0.45, each distinct phrase in the text 0.2 (up to four), a
   classification category that implies the topic adds its weight (0.6 for a
   results or guidance category, 0.3 for `regulatory_legal`), and a negative
   phrase such as "results of meeting" subtracts 0.4. Scores cap at 0.95. Each
   rule match keeps the source sentence that supports it.
2. With `CONTENT_TOPICS_LLM_ENABLED` on and an LLM switched on, the
   `TopicTagging` kind (`llm-content-topics-v1`) asks for at most three
   topics, each with a confidence, a verbatim quotation and a short event
   label. The rules' topics are offered as hints. A quotation not found in the
   source is dropped and its topic keeps 60% of its confidence. A topic the
   rules agree with gains 0.1. A topic only the rules found is kept when its
   rules score is at least 0.8, which only a category with supporting words
   reaches.
3. With no LLM, or an answer that cannot be parsed, or a failed call, the
   rules decide alone.
4. Only topics of at least `CONTENT_TOPIC_MIN_CONFIDENCE` (0.5) are recorded.

The analysis worker tags each artifact after recording its analysis, through
the `topics` port of `lambdas.artifact_analysis.AnalysisPorts`. A tagging
failure never fails the analysis; the worker logs `content_topics_failed` with
the error type. With an LLM switched on, tagging is one extra call per
analysed artifact (12,000 input characters, 2,048 output tokens).

## Clusters

`parsing.content_topics.clustering` is pure. An artifact's words are its event
label and title without stopwords. It joins the cluster of the same ticker and
topic whose stored words overlap most (shared words over the smaller set, at
least 0.3), among clusters seen within `CONTENT_TOPIC_CLUSTER_WINDOW_DAYS`
(14) of its publication; otherwise it starts a cluster. The newest member's
event label names the cluster. `app.crud.content_topic.record_topics` takes a
transaction-scoped advisory lock per ticker and topic, so two workers cannot
both start a cluster for one development. Artifacts with no ticker (public
discussion linked only by a mention) are tagged but not clustered.

## Storage

Migration `86d9contenttopics` adds:

- `artifact_content_topics`: one row per artifact and topic, with confidence,
  method (`llm` or `rules`), evidence, event label, version and model;
- `content_topic_clusters`: ticker, topic, label, stored words, first and last
  publication;
- `content_topic_cluster_members`: which artifacts are in which cluster.

Row level security is on and the Supabase Data API roles have no access, as
for every other table. A tagged artifact's metadata records
`content_topics_version`, `content_topics_method`, `content_topics_model` and
`content_topics_tagged_at`.

## Reading

- `GET /tickers/symbol/{symbol}/topics?days=90` answers every topic with its
  distinct records in the last 30 days and the 30 before, a trend (`new`,
  `rising`, `steady`, `falling` or `quiet`) and up to five clusters seen in
  the window, each with up to five records, their evidence and sources.
- `GET /announcements/?topic=<identifier>` filters the market feed. Feed and
  news-feed items list their `topics`, most confident first.
- The deep dive shows "Topics and developments" above the research history.
  Feed cards and source records show topic chips that link to the filtered
  feed.

## Tagging stored artifacts

```bash
cd backend
python -m tools.tag_content_topics --dry-run [--ticker CSL]
python -m tools.tag_content_topics --apply [--ticker CSL] [--limit 1000]
python -m tools.tag_content_topics --apply --llm --limit 50
```

It selects analysed artifacts with text that were not excluded from the feed
and whose stored tagging version is not current, oldest published first, in
committed batches. A dry run asks no LLM. `--llm` is capped at 200 artifacts a
run; it replaces rules-decided topics, and a rules run never replaces an LLM's.
`--retag` tags again what the current version already tagged.

## Evaluating

```bash
cd backend
python -m tools.evaluate_content_topics --min-f1 0.9
python -m tools.evaluate_content_topics --llm --output /tmp/topics-llm.json
```

The fixtures in `backend/tests/fixtures/content_topics/manifest.json` are 38
synthetic excerpts with labelled topics, including eight with none.
`test_content_topic_rules.py` holds the rules to a micro-averaged F1 of at
least 0.9 and, per topic, precision of at least 0.9 and recall of at least
0.75. The rules were tuned on these fixtures, so the scores overstate how they
do on new documents; the LLM is the primary tagger and `--llm` measures it.

## Adding or changing a topic

1. Add the identifier to `ContentTopic` in `app/content_topic_vocabulary.py`
   and a `TopicDefinition` to `parsing/content_topics/taxonomy.py`.
2. Write a migration that widens the two topic CHECK constraints.
3. Add at least five labelled fixtures, and negatives that must not match.
4. Change `RULES_VERSION`, and `TopicTagging.prompt_version` when the prompt
   changes, so the tagging command finds artifacts to tag again.
5. Add the topic to `frontend/src/app/lib/contentTopics.js`.
