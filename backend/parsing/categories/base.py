from __future__ import annotations

from abc import ABC, abstractmethod


class ReportCategory(ABC):
    """Base class for the metric extractors retained during classification migration."""

    name: str

    @classmethod
    @abstractmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        """
        Extract structured data from the report text.

        Returns a plain Python dict. client is a Groq instance or None.
        Classification never calls a remote model. Extractors should remain
        deterministic unless a separate extraction feature changes that contract.
        """
        ...
