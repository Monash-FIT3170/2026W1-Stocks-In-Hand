from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger("document_pipeline")
LOGGER.setLevel(logging.INFO)
_RUNTIME_CONFIGURATION_LOADED = False


class PermanentDocumentError(ValueError):
    """A message or document retry cannot fix."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunsplit(
        (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower(),
            parsed.path or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def log_event(
    *,
    stage: str,
    event: str,
    started_at: float | None = None,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    payload: dict[str, Any] = {"stage": stage, "event": event, **fields}
    if started_at is not None:
        payload["duration_ms"] = round((time.monotonic() - started_at) * 1000)
    LOGGER.log(level, json.dumps(payload, default=str, separators=(",", ":")))


def receive_attempt(record: dict[str, Any]) -> int:
    value = record.get("attributes", {}).get("ApproximateReceiveCount", "1")
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return 1


def correlation_id(record: dict[str, Any]) -> str:
    return str(record.get("messageId") or "unknown")


def load_runtime_configuration() -> None:
    """Resolve encrypted runtime values before importing the database layer."""
    global _RUNTIME_CONFIGURATION_LOADED
    if _RUNTIME_CONFIGURATION_LOADED:
        return

    parameter_names = {
        "DATABASE_URL": os.getenv("DATABASE_URL_PARAMETER", ""),
        "GROQ_API_KEY": os.getenv("GROQ_API_KEY_PARAMETER", ""),
        "BREVO_API_KEY": os.getenv("BREVO_API_KEY_PARAMETER", ""),
    }
    missing = {
        variable: parameter
        for variable, parameter in parameter_names.items()
        if parameter and variable not in os.environ
    }
    if not missing:
        _RUNTIME_CONFIGURATION_LOADED = True
        return

    ssm = boto3.client("ssm")
    for variable, parameter in missing.items():
        try:
            response = ssm.get_parameter(Name=parameter, WithDecryption=True)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if variable == "GROQ_API_KEY" and code == "ParameterNotFound":
                os.environ[variable] = ""
                continue
            raise
        os.environ[variable] = response["Parameter"]["Value"]
    _RUNTIME_CONFIGURATION_LOADED = True


@contextmanager
def database_session() -> Iterator[Any]:
    load_runtime_configuration()
    # Import after DATABASE_URL has been loaded because settings are evaluated
    # when the database module is imported.
    from app.database.connection import SessionLocal

    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
