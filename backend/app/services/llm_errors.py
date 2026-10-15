"""Errors shared by the LLM provider adapters."""


class LLMUnavailableError(RuntimeError):
    """The configured LLM provider is switched off or missing credentials.

    Analysis treats this as "no summary" and still stores sentiment, instead of
    retrying a message that can never succeed until configuration changes.
    """


class PromptTooLargeError(ValueError):
    """The provider will not take a prompt this long.

    ``max_chars`` is the longest prompt it accepts, so the generation module
    can shorten the source text, keep the instructions, and ask once more.
    """

    def __init__(self, message: str, *, max_chars: int) -> None:
        super().__init__(message)
        self.max_chars = max_chars
