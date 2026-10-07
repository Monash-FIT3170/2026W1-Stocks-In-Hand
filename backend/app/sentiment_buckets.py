"""The themes a ticker's sentiment is broken down by.

The category sentiment view groups a ticker's analysed artifacts into these
buckets, and the LLM category split sorts evidence into the same ones.
"""

SENTIMENT_BUCKETS: tuple[str, ...] = (
    "revenue",
    "strategy",
    "risk",
    "dividend",
    "organisational",
)
