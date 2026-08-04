"""Tests for artifact storage repair helpers."""

from parsing.storage import should_replace_artifact_title


def test_oversized_artifact_title_is_replaced_by_clean_headline() -> None:
    existing = "EXCHANGE RELEASES " + ("long description " * 20)
    incoming = "BHP Operational Review for the half year ended 31 December 2025"

    assert should_replace_artifact_title(existing, incoming) is True


def test_normal_artifact_title_is_not_replaced() -> None:
    assert should_replace_artifact_title(
        "BHP Operational Review",
        "Different short title",
    ) is False
