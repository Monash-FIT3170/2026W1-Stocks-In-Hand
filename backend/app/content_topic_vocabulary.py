"""The words every content topic layer shares.

A content topic is what an artifact is about, across kinds: an announcement,
a news story or a public discussion post can each be about earnings, a court
case or a regulator at once. It is separate from an announcement's category,
which is the one kind of document the classification rules decide it is, and
from a sentiment bucket.

``parsing.content_topics`` defines each topic's rules with the same
identifiers; a test holds the two lists equal. They are kept apart because
the scraper image ships ``app`` but not ``parsing``, and models import this
module.

The CHECK constraints migration ``86d9contenttopics`` adds accept exactly
``CONTENT_TOPICS`` and ``TOPIC_METHODS``, so a new member needs a migration
too.
"""

from typing import Literal, get_args

ContentTopic = Literal[
    "earnings_guidance",
    "litigation",
    "regulation",
    "product_launch",
    "macro_exposure",
]
CONTENT_TOPICS: tuple[str, ...] = get_args(ContentTopic)

# How a recorded topic was decided: by the LLM, or by the rules alone when no
# LLM is switched on or its answer could not be used.
TopicMethod = Literal["llm", "rules"]
TOPIC_METHODS: tuple[str, ...] = get_args(TopicMethod)

# Keys a tagged artifact's metadata records, so a tagging run can find the
# artifacts an older version tagged, or that were never tagged.
TOPICS_VERSION_KEY = "content_topics_version"
TOPICS_METHOD_KEY = "content_topics_method"
TOPICS_MODEL_KEY = "content_topics_model"
TOPICS_TAGGED_AT_KEY = "content_topics_tagged_at"
