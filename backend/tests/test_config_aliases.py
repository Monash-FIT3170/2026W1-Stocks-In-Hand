"""Tests for supported environment variable aliases."""

from app.core.config import _first_env


def test_first_env_uses_marketaux_api_key_alias(monkeypatch) -> None:
    monkeypatch.delenv("MARKETAUX_API_TOKEN", raising=False)
    monkeypatch.setenv("MARKETAUX_API_KEY", "alias-token")

    assert _first_env("MARKETAUX_API_TOKEN", "MARKETAUX_API_KEY") == "alias-token"


def test_first_env_prefers_marketaux_api_token(monkeypatch) -> None:
    monkeypatch.setenv("MARKETAUX_API_TOKEN", "preferred-token")
    monkeypatch.setenv("MARKETAUX_API_KEY", "alias-token")

    assert _first_env("MARKETAUX_API_TOKEN", "MARKETAUX_API_KEY") == "preferred-token"
