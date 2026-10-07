"""The interface every public discussion source implements.

A source fetches posts for a target (a search query, tag, subreddit or
feed), validates the target, and turns each fetched post into a
``CollectedPost``: the artifact to store, its identity (content hash) and
its engagement. ``app.services.discussion_collector`` does everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.schemas.artifact import ArtifactCreate


class InvalidTargetError(ValueError):
    """The target or limit is not one this source may collect."""


class MalformedPostError(ValueError):
    """A fetched post lacks what the source needs to store it."""


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    platform_type: str
    base_url: str


@dataclass(frozen=True)
class CollectedPost:
    """One fetched post, ready to store.

    The artifact's ``content_hash`` identifies the post across collections;
    its format must not change, or every stored post would be stored again.
    """

    artifact: ArtifactCreate
    # How much attention the post drew, comparable across sources so posts
    # for a ticker can be ranked together.
    engagement: int

    @property
    def content_hash(self) -> str:
        return self.artifact.content_hash


@runtime_checkable
class DiscussionSource(Protocol):
    source_type: str

    def target(self, value: str, limit: int) -> str:
        """The normalised target, or InvalidTargetError."""

    def platform(self, target: str) -> PlatformSpec: ...

    def source_url(self, target: str) -> str:
        """The page a collection run records as its source."""

    def fetch(self, target: str, limit: int) -> list[dict[str, Any]]:
        """Fetch up to ``limit`` raw posts from the site."""

    def post(self, raw: dict[str, Any], target: str) -> CollectedPost:
        """Turn one raw post into a CollectedPost, or MalformedPostError."""


def require_limit(limit: int, maximum: int) -> None:
    if not 1 <= limit <= maximum:
        raise InvalidTargetError(f"limit must be between 1 and {maximum}")
