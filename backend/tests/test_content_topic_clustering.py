"""Topic cluster decisions, as pure functions."""

from datetime import datetime, timedelta, timezone

from parsing.content_topics import (
    Candidate,
    choose_cluster,
    decode_signature,
    encode_signature,
    merged_signature,
    signature,
    similarity,
)
from parsing.content_topics.clustering import MAX_SIGNATURE_WORDS

DAY = datetime(2040, 3, 10, tzinfo=timezone.utc)


def _candidate(name: str, words: str, *, first: int = 0, last: int = 0) -> Candidate[str]:
    return Candidate(
        cluster_id=name,
        signature=signature(words),
        first_published_at=DAY + timedelta(days=first),
        last_published_at=DAY + timedelta(days=last),
    )


def test_a_signature_keeps_distinctive_words_and_short_words_with_digits() -> None:
    words = signature("FY26 production guidance lowered", "BHP Group Limited - ASX Announcement")

    assert words == frozenset({"fy26", "production", "guidance", "lowered", "bhp"})
    assert "q3" in signature("Q3 sales update")
    assert signature(None, "") == frozenset()


def test_similarity_divides_by_the_smaller_signature() -> None:
    small = signature("guidance lowered")
    large = signature("FY26 production guidance lowered after flooding at the mine")

    assert similarity(small, large) == 1.0
    assert similarity(small, frozenset()) == 0.0
    assert similarity(signature("copper output"), signature("class action")) == 0.0


def test_an_artifact_joins_the_most_similar_cluster_in_its_window() -> None:
    candidates = [
        _candidate("guidance", "FY26 production guidance lowered", last=-2),
        _candidate("flooding", "Mine flooding halts production", last=-1),
    ]

    chosen = choose_cluster(
        candidates, signature("Miner lowers FY26 guidance"), DAY, window_days=14
    )

    assert chosen == "guidance"


def test_ties_go_to_the_cluster_seen_most_recently() -> None:
    candidates = [
        _candidate("older", "class action filed", last=-5),
        _candidate("newer", "class action filed", last=-1),
    ]

    assert choose_cluster(candidates, signature("class action filed"), DAY, window_days=14) == "newer"


def test_an_artifact_outside_the_window_or_too_different_starts_a_new_cluster() -> None:
    stale = _candidate("stale", "class action filed", first=-40, last=-30)
    different = _candidate("different", "ACCC merger review", last=-1)

    assert choose_cluster([stale], signature("class action filed"), DAY, window_days=14) is None
    assert choose_cluster([different], signature("class action filed"), DAY, window_days=14) is None


def test_an_earlier_artifact_can_join_a_cluster_within_the_window_before_it() -> None:
    later = _candidate("later", "class action settlement", first=5, last=8)

    chosen = choose_cluster([later], signature("class action settlement"), DAY, window_days=14)

    assert chosen == "later"


def test_a_merged_signature_keeps_its_words_and_is_capped() -> None:
    current = frozenset(f"word{index:02d}" for index in range(MAX_SIGNATURE_WORDS - 2))
    added = frozenset({"alpha", "beta", "gamma", "word00"})

    merged = merged_signature(current, added)

    assert current <= merged
    assert len(merged) == MAX_SIGNATURE_WORDS
    assert merged - current == {"alpha", "beta"}


def test_a_signature_round_trips_through_its_stored_form() -> None:
    words = signature("ACCC opposes acquisition")

    stored = encode_signature(words)

    assert stored == "accc acquisition opposes"
    assert decode_signature(stored) == words
    assert decode_signature(None) == frozenset()
