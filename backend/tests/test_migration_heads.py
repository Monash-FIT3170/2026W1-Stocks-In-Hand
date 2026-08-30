"""Regression checks for the integrated Alembic migration graph."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_integrated_migration_graph_has_one_head() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert heads == ["86d7m4q2xmerge"]
