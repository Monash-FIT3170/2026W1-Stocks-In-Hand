"""Regression tests for the artifact-summary schema-drift repair."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "86d8promptversion_repair_artifact_summary_prompt_version.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location(
        "prompt_version_schema_repair_migration",
        MIGRATION_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repair_adds_prompt_version_when_deployed_schema_is_missing_it(
    monkeypatch,
) -> None:
    migration = _migration()
    bind = object()
    inspector = MagicMock()
    inspector.get_columns.return_value = [
        {"name": "id"},
        {"name": "summary_text"},
    ]
    add_column = MagicMock()

    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "add_column", add_column)
    monkeypatch.setattr(migration.sa, "inspect", lambda value: inspector)

    migration.upgrade()

    inspector.get_columns.assert_called_once_with("artifact_summaries")
    add_column.assert_called_once()
    table_name, column = add_column.call_args.args
    assert table_name == "artifact_summaries"
    assert column.name == "prompt_version"
    assert column.nullable is True


def test_repair_is_idempotent_for_fresh_databases(monkeypatch) -> None:
    migration = _migration()
    inspector = MagicMock()
    inspector.get_columns.return_value = [
        {"name": "id"},
        {"name": "prompt_version"},
    ]
    add_column = MagicMock()

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration.op, "add_column", add_column)
    monkeypatch.setattr(migration.sa, "inspect", lambda _value: inspector)

    migration.upgrade()

    add_column.assert_not_called()


def test_repair_follows_the_integrated_migration_head() -> None:
    migration = _migration()

    assert migration.down_revision == "86d7m4q2xpublic"
