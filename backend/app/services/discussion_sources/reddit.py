"""Reddit: hot posts in a subreddit, read through the Reddit API with praw."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import praw

from app.core.config import settings
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType

from .base import (
    CollectedPost,
    InvalidTargetError,
    MalformedPostError,
    PlatformSpec,
    require_limit,
)


def content_hash(post_id: str) -> str:
    return hashlib.sha256(f"reddit:{post_id}".encode()).hexdigest()


class RedditSource:
    source_type = "reddit"

    def configured(self) -> bool:
        return bool(settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET)

    def target(self, value: str, limit: int) -> str:
        subreddit = value.strip()
        if not subreddit or not subreddit.replace("_", "").isalnum():
            raise InvalidTargetError(
                "subreddit must contain only letters, numbers or underscores"
            )
        require_limit(limit, 100)
        return subreddit

    def platform(self, target: str) -> PlatformSpec:
        return PlatformSpec(name="Reddit", platform_type="social", base_url="https://reddit.com")

    def source_url(self, target: str) -> str:
        return f"https://www.reddit.com/r/{target}"

    def client(self) -> praw.Reddit:
        return praw.Reddit(
            client_id=settings.REDDIT_CLIENT_ID,
            client_secret=settings.REDDIT_CLIENT_SECRET,
            user_agent=settings.REDDIT_USER_AGENT,
        )

    def fetch(self, target: str, limit: int) -> list[dict[str, Any]]:
        if not self.configured():
            raise RuntimeError("REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be configured")
        posts = []
        for submission in self.client().subreddit(target).hot(limit=limit):
            posts.append(
                {
                    "id": submission.id,
                    "title": submission.title,
                    "body": submission.selftext[:1000] if submission.selftext else "",
                    "score": submission.score,
                    "upvote_ratio": submission.upvote_ratio,
                    "num_comments": submission.num_comments,
                    "url": f"https://reddit.com{submission.permalink}",
                    "external_url": submission.url if not submission.is_self else None,
                    "author": str(submission.author) if submission.author else "[deleted]",
                    "flair": submission.link_flair_text,
                    "is_self": submission.is_self,
                    "created_utc": submission.created_utc,
                    "subreddit": target,
                }
            )
        return posts

    def post(self, raw: dict[str, Any], target: str) -> CollectedPost:
        post_id = raw.get("id") or ""
        if not post_id:
            raise MalformedPostError("Reddit post has no ID")
        try:
            published_at = datetime.fromtimestamp(float(raw["created_utc"]), tz=timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise MalformedPostError(f"Reddit post {post_id} has no valid time") from exc
        return CollectedPost(
            artifact=ArtifactCreate(
                source_type=SourceType.REDDIT,
                artifact_type=ArtifactType.REDDIT_POST,
                title=raw["title"],
                url=raw["url"],
                author=raw["author"],
                raw_text=raw["body"],
                published_at=published_at,
                content_hash=content_hash(post_id),
                artifact_metadata={
                    "reddit_id": post_id,
                    "score": raw.get("score"),
                    "upvote_ratio": raw.get("upvote_ratio"),
                    "num_comments": raw.get("num_comments"),
                    "flair": raw.get("flair"),
                    "is_self": raw.get("is_self"),
                    "external_url": raw.get("external_url"),
                    "subreddit": raw.get("subreddit"),
                },
            ),
            engagement=max(int(raw.get("score") or 0), 0),
        )


REDDIT = RedditSource()
