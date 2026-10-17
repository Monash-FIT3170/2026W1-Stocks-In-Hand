"""Mastodon: public posts under a hashtag on the aus.social instance."""

from __future__ import annotations

import hashlib
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx

from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType

from .base import (
    CollectedPost,
    InvalidTargetError,
    MalformedPostError,
    PlatformSpec,
    require_limit,
)

BASE_URL = "https://aus.social"


class _PostTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(content: str) -> str:
    parser = _PostTextParser()
    parser.feed(content)
    return " ".join("".join(parser.parts).split())


def content_hash(url: str, post_id: str) -> str:
    identifier = url or f"{BASE_URL}:{post_id}"
    return hashlib.sha256(f"mastodon:{identifier}".encode()).hexdigest()


class MastodonSource:
    source_type = "mastodon"

    def target(self, value: str, limit: int) -> str:
        tag = value.strip().lstrip("#")
        if not tag:
            raise InvalidTargetError("tag must not be empty")
        if not tag.replace("_", "").isalnum():
            raise InvalidTargetError("tag must contain only letters, numbers or underscores")
        require_limit(limit, 40)
        return tag

    def platform(self, target: str) -> PlatformSpec:
        return PlatformSpec(name="Mastodon", platform_type="social", base_url=BASE_URL)

    def source_url(self, target: str) -> str:
        return f"{BASE_URL}/tags/{quote(target)}"

    def fetch(self, target: str, limit: int) -> list[dict[str, Any]]:
        response = httpx.get(
            f"{BASE_URL}/api/v1/timelines/tag/{quote(target)}",
            params={"limit": limit},
            timeout=15.0,
        )
        response.raise_for_status()
        posts = []
        for item in response.json():
            status = item.get("reblog") or item
            account = status.get("account", {})
            posts.append(
                {
                    "id": status.get("id", ""),
                    "text": strip_html(status.get("content", "")),
                    "created_at": status.get("created_at", ""),
                    "url": status.get("url", ""),
                    "author": account.get("acct") or account.get("username") or "[deleted]",
                    "display_name": account.get("display_name"),
                    "replies_count": status.get("replies_count", 0),
                    "reblogs_count": status.get("reblogs_count", 0),
                    "favourites_count": status.get("favourites_count", 0),
                    "language": status.get("language"),
                    "tags": [
                        entry.get("name") for entry in status.get("tags", []) if entry.get("name")
                    ],
                    "sensitive": status.get("sensitive", False),
                    "spoiler_text": status.get("spoiler_text", ""),
                }
            )
        return posts

    def post(self, raw: dict[str, Any], target: str) -> CollectedPost:
        post_id = raw.get("id") or ""
        if not post_id:
            raise MalformedPostError("Mastodon post has no ID")
        try:
            published_at = datetime.fromisoformat(
                str(raw["created_at"]).replace("Z", "+00:00")
            )
        except (KeyError, ValueError) as exc:
            raise MalformedPostError(f"Mastodon post {post_id} has no valid time") from exc
        url = raw.get("url") or ""
        text = raw.get("text") or ""
        engagement = sum(
            int(raw.get(name) or 0)
            for name in ("favourites_count", "reblogs_count", "replies_count")
        )
        return CollectedPost(
            artifact=ArtifactCreate(
                source_type=SourceType.MASTODON,
                artifact_type=ArtifactType.MASTODON_POST,
                title=text[:200] or "Mastodon post",
                url=url or f"{BASE_URL}/@{raw['author']}/{post_id}",
                author=raw["author"],
                raw_text=text,
                published_at=published_at,
                content_hash=content_hash(url, post_id),
                artifact_metadata={
                    "mastodon_id": post_id,
                    "display_name": raw.get("display_name"),
                    "replies_count": raw.get("replies_count", 0),
                    "reblogs_count": raw.get("reblogs_count", 0),
                    "favourites_count": raw.get("favourites_count", 0),
                    "language": raw.get("language"),
                    "tags": raw.get("tags", []),
                    "sensitive": raw.get("sensitive", False),
                    "spoiler_text": raw.get("spoiler_text", ""),
                    "search_tag": target,
                },
            ),
            engagement=engagement,
        )


MASTODON = MastodonSource()
