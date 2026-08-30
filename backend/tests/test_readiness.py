"""Readiness checks must detect the schema drift that broke staging."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from main import readiness


def test_readiness_checks_columns_repaired_after_baseline_drift() -> None:
    db = MagicMock()

    result = readiness(db)

    assert result == {
        "status": "ready",
        "checks": {"database": "ok", "artifact_schema": "ok"},
    }
    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    assert statements == [
        "SELECT is_duplicate FROM artifacts LIMIT 0",
        "SELECT prompt_version FROM artifact_summaries LIMIT 0",
    ]


def test_readiness_returns_503_when_the_schema_is_incompatible() -> None:
    db = MagicMock()
    db.execute.side_effect = SQLAlchemyError("missing column")

    with pytest.raises(HTTPException) as exc_info:
        readiness(db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database schema is not ready"
