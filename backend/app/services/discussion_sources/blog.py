"""Blogs: entries from an allowlisted RSS 2.0 or Atom feed."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree

from app.core.config import settings
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType

from .base import (
    CollectedPost,
    InvalidTargetError,
    MalformedPostError,
    PlatformSpec,
    require_limit,
)

MAX_FEED_BYTES = 2_000_000


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _strip_html(value: str) -> str:
    parser = _TextParser()
    parser.feed(value)
    return " ".join("".join(parser.parts).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(element, *names: str):
    wanted = {name.lower() for name in names}
    return next(
        (child for child in element if _local_name(child.tag) in wanted),
        None,
    )


def _child_text(element, *names: str) -> str:
    child = _child(element, *names)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def _parse_date(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _atom_url(entry) -> str:
    links = [child for child in entry if _local_name(child.tag) == "link"]
    alternate = next(
        (link for link in links if link.get("rel", "alternate") == "alternate"),
        None,
    )
    selected = alternate if alternate is not None else (links[0] if links else None)
    return selected.get("href", "") if selected is not None else ""


def parse_feed(content: bytes, *, limit: int) -> list[dict[str, Any]]:
    """Read up to ``limit`` entries from RSS 2.0 or Atom, refusing XML declarations."""
    upper_content = content.upper()
    if b"<!DOCTYPE" in upper_content or b"<!ENTITY" in upper_content:
        raise ValueError("Feed XML declarations are not allowed")
    root = ElementTree.fromstring(content)
    root_name = _local_name(root.tag)
    if root_name == "rss":
        channel = _child(root, "channel")
        entries = [] if channel is None else [
            child for child in channel if _local_name(child.tag) == "item"
        ]
        return [
            {
                "id": _child_text(entry, "guid") or _child_text(entry, "link"),
                "title": _strip_html(_child_text(entry, "title")),
                "url": _child_text(entry, "link"),
                "author": _child_text(entry, "author", "creator") or None,
                "raw_text": _strip_html(
                    _child_text(entry, "encoded", "description", "content")
                ),
                "published_at": _parse_date(
                    _child_text(entry, "pubdate", "published", "updated")
                ),
            }
            for entry in entries[:limit]
        ]
    if root_name == "feed":
        entries = [child for child in root if _local_name(child.tag) == "entry"]
        return [
            {
                "id": _child_text(entry, "id") or _atom_url(entry),
                "title": _strip_html(_child_text(entry, "title")),
                "url": _atom_url(entry),
                "author": _child_text(_child(entry, "author"), "name")
                if _child(entry, "author") is not None
                else None,
                "raw_text": _strip_html(_child_text(entry, "content", "summary")),
                "published_at": _parse_date(
                    _child_text(entry, "published", "updated")
                ),
            }
            for entry in entries[:limit]
        ]
    raise ValueError("Feed must use RSS 2.0 or Atom format")


def content_hash(feed_url: str, source_id: str) -> str:
    return hashlib.sha256(f"blog:{feed_url}:{source_id}".encode()).hexdigest()


class BlogSource:
    source_type = "blog"

    def target(self, value: str, limit: int) -> str:
        if value not in settings.PUBLIC_DISCUSSION_FEED_URLS:
            raise InvalidTargetError("feed_url is not in the configured allowlist")
        if urlparse(value).scheme != "https":
            raise InvalidTargetError("feed_url must use HTTPS")
        require_limit(limit, 100)
        return value

    def platform(self, target: str) -> PlatformSpec:
        return PlatformSpec(
            name=f"Blog: {urlparse(target).hostname or 'feed'}",
            platform_type="blog",
            base_url=target,
        )

    def source_url(self, target: str) -> str:
        return target

    def fetch(self, target: str, limit: int) -> list[dict[str, Any]]:
        response = httpx.get(
            target,
            timeout=15.0,
            follow_redirects=False,
            headers={"Accept": "application/rss+xml, application/atom+xml, application/xml"},
        )
        response.raise_for_status()
        if len(response.content) > MAX_FEED_BYTES:
            raise ValueError("Feed exceeds the 2 MB size limit")
        return parse_feed(response.content, limit=limit)

    def post(self, raw: dict[str, Any], target: str) -> CollectedPost:
        source_id = raw.get("id") or raw.get("url")
        if not source_id or not raw.get("url"):
            raise MalformedPostError("Feed entry has no ID or link")
        return CollectedPost(
            artifact=ArtifactCreate(
                source_type=SourceType.BLOG,
                artifact_type=ArtifactType.BLOG_POST,
                source_adapter="rss_atom",
                source_id=source_id,
                canonical_url=raw["url"],
                title=raw.get("title") or "Blog post",
                url=raw["url"],
                author=raw.get("author"),
                raw_text=raw.get("raw_text") or "",
                published_at=raw.get("published_at"),
                content_hash=content_hash(target, source_id),
                artifact_metadata={"feed_url": target},
            ),
            engagement=0,
        )


BLOG = BlogSource()
