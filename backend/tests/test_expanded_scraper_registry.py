"""Regression checks for the expanded company scraper registry."""

import ast
from pathlib import Path

import pytest

from scrapers.registry import REGISTRY, get_scraper


NEW_TICKERS = ("COL", "COH", "TCL", "TLS", "WDS", "RIO", "ORG", "MQG")
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "scrapers" / "registry.py"


@pytest.mark.parametrize("ticker", NEW_TICKERS)
def test_new_ticker_has_an_instantiable_scraper(ticker: str) -> None:
    scraper = get_scraper(ticker.lower())

    assert ticker in REGISTRY
    assert scraper.ticker == ticker


def test_registry_entrypoints_are_defined_once() -> None:
    tree = ast.parse(REGISTRY_PATH.read_text(encoding="utf-8"))
    function_names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    assert function_names.count("get_scraper") == 1
    assert function_names.count("discover") == 1
