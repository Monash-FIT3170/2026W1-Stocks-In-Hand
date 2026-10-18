"""The content topic taxonomy and rules, through their public interface.

Pure code: no database, network or model. The rules must keep their
precision and recall on the labelled fixtures, because with no LLM switched
on they alone decide an artifact's topics.
"""

from pathlib import Path

import pytest

from app.content_topic_vocabulary import CONTENT_TOPICS
from parsing.content_topics import (
    RULES_MIN_SCORE,
    TOPIC_IDENTIFIERS,
    TOPICS,
    TopicInput,
    detect_topics,
    topic_definition,
    topic_label,
)
from parsing.content_topics.detection import MAX_EVIDENCE_CHARS, MAX_RULES_CHARS
from tools.evaluate_content_topics import (
    DEFAULT_MANIFEST,
    evaluate,
    load_manifest,
    rules_predictor,
)

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "86d9contenttopics_add_content_topics.py"
)


def _topics(title: str, text: str = "", category: str | None = None) -> dict[str, float]:
    return {
        match.topic: match.score
        for match in detect_topics(TopicInput(title=title, text=text, category=category))
    }


def test_the_taxonomy_and_the_stored_vocabulary_name_the_same_topics() -> None:
    assert TOPIC_IDENTIFIERS == CONTENT_TOPICS
    assert set(CONTENT_TOPICS) == {
        "earnings_guidance",
        "litigation",
        "regulation",
        "product_launch",
        "macro_exposure",
    }


def test_the_migration_checks_the_vocabulary_it_was_written_for() -> None:
    """A new topic needs a migration that widens the CHECK constraints."""
    source = MIGRATION.read_text(encoding="utf-8")
    for topic in CONTENT_TOPICS:
        assert f'"{topic}"' in source


def test_the_migration_keeps_the_new_tables_out_of_the_data_api() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for table in (
        "artifact_content_topics",
        "content_topic_clusters",
        "content_topic_cluster_members",
    ):
        assert f'"{table}"' in source
    assert "for table in TABLES:" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "REVOKE ALL PRIVILEGES ON TABLE public.{table} FROM anon" in source
    assert "REVOKE ALL PRIVILEGES ON TABLE public.{table} FROM authenticated" in source


def test_every_topic_has_a_label_a_description_and_rules() -> None:
    for definition in TOPICS:
        assert definition.label and definition.description
        assert definition.title_phrases or definition.body_phrases
        assert topic_definition(definition.identifier) is definition
    assert topic_definition("unknown") is None
    assert topic_label("earnings_guidance") == "Earnings and guidance"
    assert topic_label("something_new") == "Something new"


def test_a_results_category_alone_suggests_earnings() -> None:
    assert _topics("Appendix 4D", category="HalfYearResults") == {"earnings_guidance": 0.6}
    # The stable identifier works as well as the stored compatibility name.
    assert _topics("Appendix 4D", category="half_year_results") == {"earnings_guidance": 0.6}


def test_an_unknown_or_unrelated_category_gives_no_hint() -> None:
    assert _topics("Appendix 4D", category="UNKNOWN") == {}
    assert _topics("Appendix 4D", category="news_article") == {}
    assert _topics("Appendix 4D", category="DividendAnnouncement") == {}


def test_a_title_phrase_with_supporting_text_reaches_the_recording_threshold() -> None:
    topics = _topics(
        "Shareholder class action filed",
        "Proceedings were filed in the Federal Court of Australia.",
    )

    assert topics["litigation"] >= 0.5


def test_one_passing_phrase_in_long_text_is_not_a_topic() -> None:
    topics = _topics(
        "Appointment of Company Secretary",
        "The Company Secretary is responsible for compliance with the Listing Rules.",
    )

    assert "regulation" not in topics or topics["regulation"] < 0.5


def test_a_negative_phrase_cancels_a_misleading_title_word() -> None:
    assert "earnings_guidance" not in _topics(
        "Results of Meeting", "All resolutions were decided by poll and passed."
    )


def test_a_plural_matches_its_singular_phrase() -> None:
    topics = _topics(
        "Iron ore prices and tariffs weigh on outlook",
        "Iron ore prices fell as tariffs on steel exports were raised.",
    )

    assert topics["macro_exposure"] >= 0.5


def test_acronym_rules_match_only_the_exact_acronym() -> None:
    assert "regulation" in _topics("ASIC review", "ASIC has commenced a review.")
    # A lower-case word that happens to spell an acronym is not one.
    assert "regulation" not in _topics("Basic review", "A basic review of costs.")


def test_scores_are_capped_below_certainty_and_sorted_strongest_first() -> None:
    matches = detect_topics(
        TopicInput(
            title="Full Year Results and FY27 guidance",
            text=(
                "Revenue rose. Net profit after tax was $1 billion. EBITDA increased. "
                "Earnings per share rose. The outlook is unchanged. "
                "The Federal Court dismissed a claim."
            ),
            category="FullYearResults",
        )
    )

    assert matches[0].topic == "earnings_guidance"
    assert matches[0].score == 0.95
    assert [match.score for match in matches] == sorted(
        (match.score for match in matches), reverse=True
    )
    assert all(match.score >= RULES_MIN_SCORE for match in matches)


def test_evidence_is_the_source_sentence_holding_the_first_text_match() -> None:
    text = (
        "The Company provides this update. "
        "The ACCC has opposed the proposed acquisition of the regional stores. "
        "Further details will follow."
    )
    [match] = [
        match
        for match in detect_topics(TopicInput(title="ACCC decision", text=text))
        if match.topic == "regulation"
    ]

    assert match.evidence == "The ACCC has opposed the proposed acquisition of the regional stores."
    assert match.evidence in text
    assert "text:accc" in match.rules and "title:accc" in match.rules


def test_evidence_from_a_long_sentence_keeps_the_matching_phrase() -> None:
    sentence = "word " * 200 + "the shareholder class action " + "word " * 200 + "."
    [match] = [
        match
        for match in detect_topics(TopicInput(title="Class action update", text=sentence))
        if match.topic == "litigation"
    ]

    assert len(match.evidence) <= MAX_EVIDENCE_CHARS
    assert "class action" in match.evidence


def test_only_the_start_of_a_long_document_is_read() -> None:
    padding = "Operational commentary without topic words. " * (MAX_RULES_CHARS // 40)
    text = padding + "A shareholder class action was filed in the Federal Court."

    assert "litigation" not in _topics("Annual Report", text)


def test_malformed_input_finds_nothing_and_does_not_raise() -> None:
    assert detect_topics(TopicInput(title="", text="")) == ()
    assert detect_topics(TopicInput(title=None, text=None)) == ()  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def report() -> dict:
    return evaluate(load_manifest(DEFAULT_MANIFEST), rules_predictor())


def test_the_fixture_set_covers_every_topic_and_negatives() -> None:
    fixtures = load_manifest(DEFAULT_MANIFEST)
    for topic in CONTENT_TOPICS:
        assert sum(topic in fixture["expected_topics"] for fixture in fixtures) >= 5, topic
    assert sum(not fixture["expected_topics"] for fixture in fixtures) >= 5
    assert len({fixture["id"] for fixture in fixtures}) == len(fixtures)


def test_the_rules_keep_their_precision_and_recall_on_the_fixtures(report: dict) -> None:
    assert report["micro"]["f1"] >= 0.9, report["mismatches"]
    for topic, scores in report["topics"].items():
        assert scores["precision"] >= 0.9, (topic, report["mismatches"])
        assert scores["recall"] >= 0.75, (topic, report["mismatches"])


def test_the_rules_tag_no_topic_on_the_negative_fixtures() -> None:
    predict = rules_predictor()
    for fixture in load_manifest(DEFAULT_MANIFEST):
        if not fixture["expected_topics"]:
            predicted = predict(
                TopicInput(
                    title=fixture.get("title") or "",
                    text=fixture["text"],
                    category=fixture.get("category"),
                )
            )
            assert predicted == set(), fixture["id"]
