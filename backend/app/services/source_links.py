"""Browser-ready publisher links, separate from immutable document identity."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TCL_PUBLIC_APP_ID = "a50955429d255a58"
_TCL_DOCUMENT_PATH = re.compile(
    r"^/api/v5/symbols/tcl\.asx/announcements/[A-Za-z0-9_-]+/document/?$"
)


def safe_source_url(value: object) -> str | None:
    """Only expose absolute HTTP(S) links without embedded credentials."""
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname and not (
            parsed.username or parsed.password
        ):
            return value.strip()
    except ValueError:
        pass
    return None


def browser_source_url(value: object) -> str | None:
    """Restore public viewer parameters used by the TCL downloader."""
    url = safe_source_url(value)
    if url is None:
        return None
    parsed = urlsplit(url)
    if parsed.hostname != "yourir.info" or not _TCL_DOCUMENT_PATH.fullmatch(parsed.path):
        return url
    params = parse_qsl(parsed.query, keep_blank_values=True)
    for key, default in (("appID", TCL_PUBLIC_APP_ID), ("liveness", "live")):
        if not any(name == key and value for name, value in params):
            params = [(name, value) for name, value in params if name != key]
            params.append((key, default))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), parsed.fragment))


def artifact_source_url(artifact) -> str | None:
    """Prefer the specific document across claim and feed citation surfaces."""
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    return next((url for value in (
        getattr(artifact, "document_url", None), metadata.get("pdf_url"),
        getattr(artifact, "url", None), getattr(artifact, "canonical_url", None),
        metadata.get("source_url"),
    ) if (url := browser_source_url(value))), None)
