"""Bluesky: posts matching a search query, from the public AppView or a session."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType

from .base import (
    CollectedPost,
    InvalidTargetError,
    MalformedPostError,
    PlatformSpec,
    require_limit,
)

SEARCH_PATH = "/xrpc/app.bsky.feed.searchPosts"
SESSION_PATH = "/xrpc/com.atproto.server.createSession"


def content_hash(uri: str) -> str:
    return hashlib.sha256(f"bluesky:{uri}".encode()).hexdigest()


class BlueskySource:
    source_type = "bluesky"

    def target(self, value: str, limit: int) -> str:
        query = value.strip()
        if not query:
            raise InvalidTargetError("query must not be empty")
        require_limit(limit, 100)
        return query

    def platform(self, target: str) -> PlatformSpec:
        return PlatformSpec(name="Bluesky", platform_type="social", base_url="https://bsky.app")

    def source_url(self, target: str) -> str:
        return f"{settings.BLUESKY_PUBLIC_API_URL}{SEARCH_PATH}"

    def search_request(self) -> tuple[str, dict[str, str]]:
        """The search URL and headers: public, or signed in with an app password."""
        identifier = settings.BLUESKY_IDENTIFIER.strip()
        app_password = settings.BLUESKY_APP_PASSWORD.strip()
        if bool(identifier) != bool(app_password):
            raise RuntimeError(
                "BLUESKY_IDENTIFIER and BLUESKY_APP_PASSWORD must be configured together"
            )
        if not identifier:
            return f"{settings.BLUESKY_PUBLIC_API_URL}{SEARCH_PATH}", {}
        response = httpx.post(
            f"{settings.BLUESKY_SERVICE_URL}{SESSION_PATH}",
            json={"identifier": identifier, "password": app_password},
            timeout=15.0,
        )
        response.raise_for_status()
        access_token = response.json().get("accessJwt")
        if not access_token:
            raise RuntimeError("Bluesky session response did not include an access token")
        return (
            f"{settings.BLUESKY_SERVICE_URL}{SEARCH_PATH}",
            {"Authorization": f"Bearer {access_token}"},
        )

    def fetch(self, target: str, limit: int) -> list[dict[str, Any]]:
        search_url, headers = self.search_request()
        response = httpx.get(
            search_url,
            params={"q": target, "limit": limit},
            headers=headers,
            timeout=15.0,
        )
        response.raise_for_status()
        posts = []
        for post in response.json().get("posts", []):
            record = post.get("record", {})
            author = post.get("author", {})
            posts.append(
                {
                    "uri": post.get("uri", ""),
                    "text": record.get("text", ""),
                    "created_at": record.get("createdAt", ""),
                    "author": author.get("handle", "[deleted]"),
                    "display_name": author.get("displayName"),
                    "reply_count": post.get("replyCount", 0),
                    "repost_count": post.get("repostCount", 0),
                    "like_count": post.get("likeCount", 0),
                    "quote_count": post.get("quoteCount", 0),
                    "langs": record.get("langs", []),
                    "tags": [
                        tag.get("tag") for tag in record.get("tags", []) if tag.get("tag")
                    ],
                }
            )
        return posts

    def post(self, raw: dict[str, Any], target: str) -> CollectedPost:
        uri = raw.get("uri") or ""
        if not uri:
            raise MalformedPostError("Bluesky post has no URI")
        try:
            created_at = datetime.fromisoformat(str(raw["created_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise MalformedPostError(f"Bluesky post {uri} has no valid time") from exc
        text = raw.get("text") or ""
        return CollectedPost(
            artifact=ArtifactCreate(
                source_type=SourceType.BLUESKY,
                artifact_type=ArtifactType.BLUESKY_POST,
                title=text[:200] or "Bluesky post",
                url=f"https://bsky.app/profile/{raw['author']}/post/{uri.rsplit('/', 1)[-1]}",
                author=raw["author"],
                raw_text=text,
                published_at=created_at,
                content_hash=content_hash(uri),
                artifact_metadata={
                    "bluesky_uri": uri,
                    "display_name": raw.get("display_name"),
                    "reply_count": raw.get("reply_count", 0),
                    "repost_count": raw.get("repost_count", 0),
                    "like_count": raw.get("like_count", 0),
                    "quote_count": raw.get("quote_count", 0),
                    "langs": raw.get("langs", []),
                    "tags": raw.get("tags", []),
                    "search_query": target,
                },
            ),
            engagement=int(raw.get("like_count") or 0),
        )


BLUESKY = BlueskySource()
