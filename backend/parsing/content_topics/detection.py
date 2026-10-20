"""Deterministic content topic hints from an artifact's title, text and category.

``detect_topics`` scores every topic by fixed weights and returns each one
that reaches ``RULES_MIN_SCORE``, strongest first, with the source passage
that supports it. The score is a rules score, not a probability: it says how
much rule evidence there is, and caps below 1 so a rules decision never
looks certain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from parsing.classification.normalization import safe_text
from parsing.classification.taxonomy import category_definition, category_for_compatibility
from parsing.content_topics.taxonomy import TOPICS, TopicDefinition, TopicRule

# The most of an artifact's text the rules read. An announcement leads with
# its substance, and a long document's later pages hold boilerplate such as
# contingent liability notes, so later text would mostly add false hints.
MAX_RULES_CHARS = 12_000
# A topic's phrase in the title is strong evidence; a phrase in the text is
# weaker and counts for more only alongside other distinct phrases.
TITLE_WEIGHT = 0.45
BODY_WEIGHT = 0.2
MAX_TITLE_HITS = 2
MAX_BODY_HITS = 4
NEGATIVE_WEIGHT = 0.4
MAX_RULES_SCORE = 0.95
RULES_MIN_SCORE = 0.35
# The longest supporting passage kept, in characters.
MAX_EVIDENCE_CHARS = 280

_SEPARATOR = r"[\s\-_‐-―]+"
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n{2,}")


@dataclass(frozen=True)
class TopicInput:
    """What the rules and the LLM read about one artifact."""

    title: str
    text: str
    # The artifact's classification category identifier or metadata category,
    # such as ``half_year_results`` or ``HalfYearResults``. None for news and
    # public discussion.
    category: str | None = None
    source_type: str | None = None


@dataclass(frozen=True)
class TopicMatch:
    """One topic the rules found, with its rules score and supporting passage."""

    topic: str
    score: float
    # Verbatim source wording around the first matching body phrase, or the
    # title when only the title matched. None when only the category matched.
    evidence: str | None
    rules: tuple[str, ...]


def detect_topics(source: TopicInput) -> tuple[TopicMatch, ...]:
    """Every topic the rules find in ``source``, strongest first."""
    title = safe_text(source.title, limit=1000)
    text = safe_text(source.text, limit=MAX_RULES_CHARS)
    category = _category_identifier(source.category)
    matches = [
        match
        for definition in TOPICS
        if (match := _score(definition, title, text, category)) is not None
    ]
    return tuple(sorted(matches, key=lambda match: (-match.score, match.topic)))


def _score(
    definition: TopicDefinition,
    title: str,
    text: str,
    category: str | None,
) -> TopicMatch | None:
    rules: list[str] = []
    score = 0.0
    if category is not None and category in definition.category_hints:
        score += definition.category_weight
        rules.append(f"category:{category}")

    # Any of the topic's phrases counts in a title, not only its title phrases.
    title_hits = _distinct_hits(
        definition.title_phrases + definition.body_phrases, title
    )[:MAX_TITLE_HITS]
    score += TITLE_WEIGHT * len(title_hits)
    rules.extend(f"title:{rule.name}" for rule, _match in title_hits)

    body_hits = _distinct_hits(definition.body_phrases, text)[:MAX_BODY_HITS]
    score += BODY_WEIGHT * len(body_hits)
    rules.extend(f"text:{rule.name}" for rule, _match in body_hits)

    negatives = _distinct_hits(definition.negative_phrases, f"{title}\n{text}")
    score -= NEGATIVE_WEIGHT * len(negatives)
    rules.extend(f"negative:{rule.name}" for rule, _match in negatives)

    score = round(min(score, MAX_RULES_SCORE), 4)
    if score < RULES_MIN_SCORE:
        return None
    if body_hits:
        evidence = _sentence_around(text, body_hits[0][1])
    elif title_hits:
        evidence = title.strip() or None
    else:
        evidence = None
    return TopicMatch(
        topic=definition.identifier,
        score=score,
        evidence=evidence,
        rules=tuple(rules),
    )


def _distinct_hits(
    rules: tuple[TopicRule, ...],
    source: str,
) -> list[tuple[TopicRule, re.Match[str]]]:
    """Each rule that matches, once per distinct phrase, in rule order."""
    hits: list[tuple[TopicRule, re.Match[str]]] = []
    seen: set[str] = set()
    for rule in rules:
        key = rule.phrase.lower()
        if key in seen:
            continue
        match = _search(source, rule)
        if match is not None:
            seen.add(key)
            hits.append((rule, match))
    return hits


def _search(source: str, rule: TopicRule) -> re.Match[str] | None:
    phrase = rule.phrase.strip()
    if not phrase or not source:
        return None
    if rule.token:
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", source)
    expression = _SEPARATOR.join(re.escape(part) for part in phrase.split())
    # A plural matches too, so "tariff" finds "tariffs" and "price" "prices".
    return re.search(
        rf"(?<![A-Za-z0-9]){expression}(?:e?s)?(?![A-Za-z0-9])",
        source,
        flags=re.IGNORECASE,
    )


def _sentence_around(text: str, match: re.Match[str]) -> str:
    """The sentence holding ``match``, as the source words it, cut to the evidence limit."""
    start = 0
    for boundary in _SENTENCE_END.finditer(text, 0, match.start()):
        start = boundary.end()
    end_boundary = _SENTENCE_END.search(text, match.end())
    end = end_boundary.start() if end_boundary else len(text)
    sentence = " ".join(text[start:end].split())
    if len(sentence) <= MAX_EVIDENCE_CHARS:
        return sentence
    # Keep the matching phrase inside a long sentence.
    phrase = " ".join(match.group(0).split())
    position = max(sentence.lower().find(phrase.lower()), 0)
    begin = max(0, min(position - MAX_EVIDENCE_CHARS // 3, len(sentence) - MAX_EVIDENCE_CHARS))
    return sentence[begin : begin + MAX_EVIDENCE_CHARS].strip()


def _category_identifier(category: str | None) -> str | None:
    """A classification category identifier from an identifier or a metadata category."""
    if not category or not isinstance(category, str):
        return None
    value = category.strip()
    stored = category_for_compatibility(value)
    if stored is not None:
        return stored.identifier
    identified = category_definition(value)
    return identified.identifier if identified is not None else None
