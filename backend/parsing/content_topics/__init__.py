"""Content topics: what an artifact is about, and grouping artifacts about one development.

Only the standard library and ``parsing`` are imported, as in
``parsing.classification``, because the API image ships this package.
"""

from .clustering import (
    Candidate,
    choose_cluster,
    decode_signature,
    encode_signature,
    merged_signature,
    signature,
    similarity,
)
from .detection import RULES_MIN_SCORE, TopicInput, TopicMatch, detect_topics
from .taxonomy import (
    RULES_VERSION,
    TOPIC_IDENTIFIERS,
    TOPICS,
    TopicDefinition,
    TopicRule,
    topic_definition,
    topic_label,
)

__all__ = [
    "Candidate",
    "RULES_MIN_SCORE",
    "RULES_VERSION",
    "TOPICS",
    "TOPIC_IDENTIFIERS",
    "TopicDefinition",
    "TopicInput",
    "TopicMatch",
    "TopicRule",
    "choose_cluster",
    "decode_signature",
    "detect_topics",
    "encode_signature",
    "merged_signature",
    "signature",
    "similarity",
    "topic_definition",
    "topic_label",
]
