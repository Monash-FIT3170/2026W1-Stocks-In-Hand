"""Readiness checks must detect the schema drift that broke staging."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from main import readiness


def test_readiness_checks_the_artifact_duplicate_column() -> None:
    db = MagicMock()

    result = readiness(db)

    assert result == {
        "status": "ready",
        "checks": {"database": "ok", "artifact_schema": "ok"},
    }
    statement = str(db.execute.call_args.args[0])
    assert statement == "SELECT is_duplicate FROM artifacts LIMIT 0"


def test_readiness_returns_503_when_the_schema_is_incompatible() -> None:
    db = MagicMock()
    db.execute.side_effect = SQLAlchemyError("missing column")

    with pytest.raises(HTTPException) as exc_info:
        readiness(db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database schema is not ready"
