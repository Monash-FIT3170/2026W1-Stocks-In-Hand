"""Topic clusters: grouping one ticker's artifacts about the same development.

A topic cluster gathers the artifacts of one ticker and one topic that report
the same development: an announcement, the news stories about it and the
posts discussing it. Each artifact's topic has a short event label, and the
cluster's signature is the set of words its members' labels and titles use.
An artifact joins the cluster whose signature its own words overlap most,
when that cluster saw an artifact within the window; otherwise it starts a
new one.

This is deterministic and needs no embeddings. It is pure, so the database
code passes the candidate clusters in and records the decision.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Generic, TypeVar

# Words that say nothing about which development an artifact reports.
_STOPWORDS = frozenset(
    """
    a about above after again against all also an and any are as at be been before
    being below between both but by can could did do does during each few for from
    further had has have having he her here hers him his how i if in into is it its
    itself just more most no nor not of off on once only or other our out over own
    same she should so some such than that the their them then there these they this
    those through to too under until up very was we were what when where which while
    who whom why will with would you your
    asx limited ltd group company companies announcement announcements update updates
    report reports release media statement says said new share shares shareholder
    shareholders investor investors market markets today year years australia australian
    """.split()
)
_WORD = re.compile(r"[a-z0-9][a-z0-9&'.-]*[a-z0-9]|[a-z0-9]")
# The most words a cluster's signature keeps, so a long-running cluster does
# not swallow every later artifact.
MAX_SIGNATURE_WORDS = 40
# How much two signatures must overlap for an artifact to join a cluster.
JOIN_SIMILARITY = 0.3

ClusterId = TypeVar("ClusterId")


@dataclass(frozen=True)
class Candidate(Generic[ClusterId]):
    """An existing cluster an artifact may join."""

    cluster_id: ClusterId
    signature: frozenset[str]
    first_published_at: datetime
    last_published_at: datetime


def signature(*texts: str | None) -> frozenset[str]:
    """The distinctive words of an event label and title, lower-cased.

    Words of one or two letters are dropped unless they hold a digit, so
    "FY26", "H1" and "Q3" are kept and "of" is not.
    """
    words: set[str] = set()
    for text in texts:
        if not text:
            continue
        for word in _WORD.findall(text.lower()):
            word = word.strip(".'-")
            if not word or word in _STOPWORDS:
                continue
            if len(word) < 3 and not any(character.isdigit() for character in word):
                continue
            words.add(word)
    return frozenset(words)


def similarity(first: frozenset[str], second: frozenset[str]) -> float:
    """How much two signatures overlap: shared words over the smaller signature.

    Dividing by the smaller one lets a short event label match a long-running
    cluster's larger signature.
    """
    if not first or not second:
        return 0.0
    return len(first & second) / min(len(first), len(second))


def merged_signature(current: Iterable[str], added: Iterable[str]) -> frozenset[str]:
    """A cluster's signature once an artifact joins, capped at ``MAX_SIGNATURE_WORDS``.

    The current words are kept first, then the added ones in sorted order, so
    the result never depends on set order.
    """
    words = list(dict.fromkeys(sorted(current)))
    for word in sorted(set(added) - set(words)):
        if len(words) >= MAX_SIGNATURE_WORDS:
            break
        words.append(word)
    return frozenset(words)


def choose_cluster(
    candidates: Sequence[Candidate[ClusterId]],
    words: frozenset[str],
    published_at: datetime,
    *,
    window_days: int,
    threshold: float = JOIN_SIMILARITY,
) -> ClusterId | None:
    """The cluster an artifact with ``words``, published at ``published_at``, joins.

    A candidate is in reach when the artifact falls within ``window_days`` of
    the cluster's dates. Of those reaching ``threshold``, the most similar
    wins, then the one seen most recently. None starts a new cluster.
    """
    window = timedelta(days=window_days)
    best: tuple[float, datetime, Candidate[ClusterId]] | None = None
    for candidate in candidates:
        if not (
            candidate.first_published_at - window
            <= published_at
            <= candidate.last_published_at + window
        ):
            continue
        score = similarity(words, candidate.signature)
        if score < threshold:
            continue
        key = (score, candidate.last_published_at, candidate)
        if best is None or key[:2] > best[:2]:
            best = key
    return best[2].cluster_id if best is not None else None


def encode_signature(words: Iterable[str]) -> str:
    """A signature as it is stored: its words sorted and joined by spaces."""
    return " ".join(sorted(set(words)))


def decode_signature(stored: str | None) -> frozenset[str]:
    """A stored signature's words."""
    return frozenset((stored or "").split())
