"""Errors shared by the LLM provider adapters."""


class LLMUnavailableError(RuntimeError):
    """The configured LLM provider is switched off or missing credentials.

    Analysis treats this as "no summary" and still stores sentiment, instead of
    retrying a message that can never succeed until configuration changes.
    """
