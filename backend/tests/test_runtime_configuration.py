"""The runtime configuration: every setting declared once and read on first use.

These tests read an environment through ``Settings.from_environment`` and
never set an environment variable for a setting. ``settings`` keeps what the
environment held at its first read, so a test that set one could leak it
into every later test. The two tests of the first read itself build the
settings again before and after they run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config
from app.core.config import (
    SECRETS,
    ConfigurationError,
    InMemoryParameterStore,
    Secret,
    Settings,
    SsmParameterStore,
    get_settings,
    reset_settings,
    settings,
)
from app.sources import SOURCES, scheduled_tickers

BACKEND = Path(__file__).resolve().parents[1]
PARAMETER = "/stocks-in-hand/test/secret"
REQUIRED_SECRETS = [secret for secret in SECRETS if not secret.optional]
OPTIONAL_SECRETS = [secret for secret in SECRETS if secret.optional]


@pytest.fixture()
def unbuilt_settings() -> Iterator[None]:
    """Settings that are built again at the next read, and again after the test."""
    reset_settings()
    yield
    reset_settings()


def test_a_bad_value_fails_at_the_first_read_not_at_import() -> None:
    script = (
        "import app.core.config as config\n"
        "try:\n"
        "    config.settings.ALERT_DAILY_BUDGET\n"
        "except config.ConfigurationError as error:\n"
        "    print(error)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env={**os.environ, "ALERT_DAILY_BUDGET": "abc"},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == (
        "Invalid runtime configuration: ALERT_DAILY_BUDGET must be a whole number"
    )


def test_an_empty_environment_gives_the_documented_defaults() -> None:
    defaults = Settings.from_environment({})

    assert defaults.DATABASE_URL == "postgresql://user:password@localhost:5432/spike"
    assert (defaults.AUTH_PROVIDER, defaults.LLM_PROVIDER) == ("legacy", "bedrock")
    assert defaults.BEDROCK_ENABLED is False
    assert defaults.BEDROCK_MODEL_ID == "openai.gpt-oss-120b-1:0"
    assert defaults.BEDROCK_SERVICE_TIER == "default"
    assert defaults.BEDROCK_MAX_PROMPT_CHARS == 30000
    assert (defaults.NOTIFICATIONS_ENABLED, defaults.NOTIFICATIONS_DRY_RUN) == (False, False)
    assert defaults.ALERT_SENDER_NAME == "Stocks In Hand"
    assert defaults.ALERT_DAILY_BUDGET == 180
    assert defaults.ALERT_MAX_PER_INVESTOR_PER_RUN == 5
    assert defaults.ALERT_DEFAULT_MIN_CONFIDENCE == 0.75
    assert defaults.ALERT_CLAIM_STALE_MINUTES == 15
    assert defaults.ALERT_VERIFICATION_TOKEN_TTL_HOURS == 24
    assert defaults.FRONTEND_BASE_URL == "http://localhost:3000"
    assert defaults.SUPPORTED_TICKERS == list(SOURCES)
    assert defaults.PUBLIC_DISCUSSION_FEED_URLS == []
    assert defaults.NEWS_FETCH_LIMIT == 10
    assert defaults.CORS_ORIGINS == ["http://localhost:3000"]
    assert (defaults.SESSION_COOKIE_NAME, defaults.SESSION_EXPIRE_DAYS) == ("stonks_session", 7)
    assert (defaults.SESSION_COOKIE_SECURE, defaults.SESSION_COOKIE_SAMESITE) == (False, "lax")
    assert defaults.SCHEDULED_TICKERS == scheduled_tickers()
    assert (defaults.MARKETAUX_ENABLED, defaults.MARKETAUX_PER_TICKER_LIMIT) == (False, 10)
    assert defaults.SCHEDULED_PUBLIC_DISCUSSION_SOURCES == ["bluesky", "mastodon"]
    assert defaults.PUBLIC_DISCUSSION_PER_SOURCE_LIMIT == 10
    assert defaults.PUBLIC_DISCUSSION_SEARCH_QUERY == "ASX"


def test_values_are_read_as_the_backend_always_read_them() -> None:
    read = Settings.from_environment(
        {
            "AUTH_PROVIDER": " Legacy ",
            "BEDROCK_SERVICE_TIER": "FLEX",
            "BLUESKY_SERVICE_URL": "https://bsky.example//",
            "NOTIFICATIONS_ENABLED": "TRUE",
            "SESSION_COOKIE_SECURE": "yes",
            "SUPPORTED_TICKERS": " csl, ,wes,CSL",
            "CORS_ORIGINS": "https://a.example, https://b.example,",
        }
    )

    assert (read.AUTH_PROVIDER, read.BEDROCK_SERVICE_TIER) == ("legacy", "flex")
    assert read.BLUESKY_SERVICE_URL == "https://bsky.example"
    assert (read.NOTIFICATIONS_ENABLED, read.SESSION_COOKIE_SECURE) == (True, False)
    assert read.SUPPORTED_TICKERS == ["CSL", "WES", "CSL"]
    assert read.CORS_ORIGINS == ["https://a.example", "https://b.example"]


def test_a_variable_that_is_set_is_read_even_when_empty() -> None:
    read = Settings.from_environment({"SUPPORTED_TICKERS": "", "SCHEDULED_TICKERS": ""})

    assert (read.SUPPORTED_TICKERS, read.SCHEDULED_TICKERS) == ([], [])


def test_the_schedule_keeps_only_catalogue_tickers_in_catalogue_order() -> None:
    read = Settings.from_environment({"SCHEDULED_TICKERS": "wes, XYZ,anz,WES"})

    assert read.SCHEDULED_TICKERS == ["ANZ", "WES"]


def test_the_public_discussion_schedule_keeps_only_known_sources() -> None:
    read = Settings.from_environment(
        {"SCHEDULED_PUBLIC_DISCUSSION_SOURCES": "blog, Reddit,unknown,"}
    )

    assert read.SCHEDULED_PUBLIC_DISCUSSION_SOURCES == ["reddit", "blog"]


@pytest.mark.parametrize(("value", "query"), [(" asx 200 ", "asx 200"), ("  ", "ASX"), ("", "ASX")])
def test_an_empty_search_query_reads_as_asx(value: str, query: str) -> None:
    read = Settings.from_environment({"PUBLIC_DISCUSSION_SEARCH_QUERY": value})

    assert read.PUBLIC_DISCUSSION_SEARCH_QUERY == query


def test_a_required_setting_must_be_set() -> None:
    assert Settings.from_environment(
        {"DISCOVERY_QUEUE_URL": "https://sqs.example/queue-a"}
    ).required("DISCOVERY_QUEUE_URL") == "https://sqs.example/queue-a"
    with pytest.raises(ConfigurationError) as rejected:
        Settings.from_environment({"DISCOVERY_QUEUE_URL": ""}).required("DISCOVERY_QUEUE_URL")

    assert rejected.value.problems == ("DISCOVERY_QUEUE_URL must be set",)


@pytest.mark.parametrize(
    ("variable", "value", "problem"),
    [
        ("AUTH_PROVIDER", "okta", "must be one of legacy, dual, cognito"),
        ("LLM_PROVIDER", "gemini", "must be one of bedrock, groq"),
        ("BEDROCK_SERVICE_TIER", "fast", "must be one of default, flex, priority"),
        ("BEDROCK_MODEL_ID", "  ", "must not be empty"),
        ("BEDROCK_MAX_PROMPT_CHARS", "999", "must be at least 1000"),
        ("ALERT_DAILY_BUDGET", "-1", "must be at least 0"),
        ("ALERT_MAX_PER_INVESTOR_PER_RUN", "0", "must be at least 1"),
        ("ALERT_CLAIM_STALE_MINUTES", "0", "must be at least 1"),
        ("ALERT_VERIFICATION_TOKEN_TTL_HOURS", "0", "must be at least 1"),
        ("ALERT_DEFAULT_MIN_CONFIDENCE", "1.5", "must be from 0 to 1"),
        ("ALERT_DEFAULT_MIN_CONFIDENCE", "high", "must be a number"),
        ("COGNITO_JWKS_CACHE_SECONDS", "five", "must be a whole number"),
        ("SESSION_EXPIRE_DAYS", "", "must be a whole number"),
        ("MARKETAUX_PER_TICKER_LIMIT", "0", "must be at least 1"),
        ("MARKETAUX_PER_TICKER_LIMIT", "26", "must be at most 25"),
        ("MARKETAUX_PER_TICKER_LIMIT", "abc", "must be a whole number"),
        ("PUBLIC_DISCUSSION_PER_SOURCE_LIMIT", "0", "must be at least 1"),
        ("PUBLIC_DISCUSSION_PER_SOURCE_LIMIT", "26", "must be at most 25"),
        ("PUBLIC_DISCUSSION_PER_SOURCE_LIMIT", "abc", "must be a whole number"),
        ("PUBLIC_DISCUSSION_SEARCH_QUERY", "x" * 101, "must be at most 100 characters"),
    ],
)
def test_a_bad_value_is_rejected_with_its_limit(variable: str, value: str, problem: str) -> None:
    with pytest.raises(ConfigurationError) as rejected:
        Settings.from_environment({variable: value})

    assert rejected.value.problems == (f"{variable} {problem}",)


def test_every_bad_value_is_reported_and_none_is_echoed() -> None:
    with pytest.raises(ConfigurationError) as rejected:
        Settings.from_environment(
            {"ALERT_DAILY_BUDGET": "postgres-password", "LLM_PROVIDER": "brevo-key"}
        )

    assert rejected.value.problems == (
        "ALERT_DAILY_BUDGET must be a whole number",
        "LLM_PROVIDER must be one of bedrock, groq",
    )
    assert "password" not in str(rejected.value)
    assert "brevo-key" not in str(rejected.value)
    assert rejected.value.__context__ is None


def test_a_configuration_error_is_not_a_value_error() -> None:
    """Routes turn ValueError into a 400, which would hide a broken deployment."""
    assert not issubclass(ConfigurationError, ValueError)


@pytest.mark.parametrize("provider", ["dual", "cognito"])
def test_cognito_sign_in_needs_its_pool_its_client_and_a_jwks_cache(provider: str) -> None:
    with pytest.raises(ConfigurationError) as rejected:
        Settings.from_environment({"AUTH_PROVIDER": provider, "COGNITO_JWKS_CACHE_SECONDS": "0"})

    assert rejected.value.problems == (
        f"COGNITO_USER_POOL_ID must be set when AUTH_PROVIDER is {provider}",
        f"COGNITO_APP_CLIENT_ID must be set when AUTH_PROVIDER is {provider}",
        f"COGNITO_JWKS_CACHE_SECONDS must be greater than zero when AUTH_PROVIDER is {provider}",
    )
    configured = Settings.from_environment(
        {
            "AUTH_PROVIDER": provider.upper(),
            "COGNITO_USER_POOL_ID": " pool ",
            "COGNITO_APP_CLIENT_ID": "client",
        }
    )
    assert (configured.COGNITO_USER_POOL_ID, configured.COGNITO_APP_CLIENT_ID) == ("pool", "client")


def test_legacy_sign_in_needs_no_cognito_settings() -> None:
    assert Settings.from_environment({"COGNITO_JWKS_CACHE_SECONDS": "0"}).AUTH_PROVIDER == "legacy"


def test_marketaux_api_key_is_an_alias_for_the_marketaux_token() -> None:
    def token(environ: dict[str, str]) -> str:
        return Settings.from_environment(environ).MARKETAUX_API_TOKEN

    assert token({"MARKETAUX_API_KEY": " alias-token "}) == "alias-token"
    assert token({"MARKETAUX_API_TOKEN": "", "MARKETAUX_API_KEY": "alias-token"}) == "alias-token"
    assert token({"MARKETAUX_API_TOKEN": "token", "MARKETAUX_API_KEY": "alias-token"}) == "token"
    assert token({}) == ""


def test_patching_settings_patches_the_built_settings_and_restores_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = get_settings()
    budget, sender = built.ALERT_DAILY_BUDGET, built.ALERT_SENDER_NAME

    with patch.object(settings, "ALERT_DAILY_BUDGET", 7):
        assert built.ALERT_DAILY_BUDGET == 7
    with patch.multiple(settings, ALERT_DAILY_BUDGET=8, ALERT_SENDER_NAME="Test"):
        assert (built.ALERT_DAILY_BUDGET, built.ALERT_SENDER_NAME) == (8, "Test")
    assert (built.ALERT_DAILY_BUDGET, built.ALERT_SENDER_NAME) == (budget, sender)

    monkeypatch.setattr(settings, "ALERT_DAILY_BUDGET", 9)
    monkeypatch.setattr(settings, "NOT_A_SETTING", "added", raising=False)
    assert (built.ALERT_DAILY_BUDGET, getattr(built, "NOT_A_SETTING")) == (9, "added")
    monkeypatch.undo()
    assert built.ALERT_DAILY_BUDGET == budget
    assert not hasattr(built, "NOT_A_SETTING")

    with pytest.raises(AttributeError):
        with patch.object(settings, "NOT_A_SETTING", 1):
            pass


def test_patching_before_the_first_read_builds_the_settings_first(
    unbuilt_settings: None,
) -> None:
    with patch.object(settings, "ALERT_DAILY_BUDGET", 7):
        assert get_settings().ALERT_DAILY_BUDGET == 7

    assert get_settings().ALERT_DAILY_BUDGET == (
        Settings.from_environment(os.environ).ALERT_DAILY_BUDGET
    )


def _setting(secret: Secret, environ: dict[str, str], **kwargs: Any) -> Any:
    return getattr(Settings.from_environment(environ, **kwargs), secret.setting)


@pytest.mark.parametrize("secret", SECRETS, ids=lambda secret: secret.setting)
def test_a_secret_is_read_from_the_parameter_its_variable_names(secret: Secret) -> None:
    parameters = InMemoryParameterStore({PARAMETER: "https://value.example/a"})
    environ = {secret.variable: PARAMETER}

    read = _setting(secret, environ, parameters=parameters)

    assert read == _setting(secret, {secret.setting: "https://value.example/a"})
    assert parameters.requested == [PARAMETER]
    assert environ == {secret.variable: PARAMETER}


@pytest.mark.parametrize("value", ["https://value.example/local", ""])
@pytest.mark.parametrize("secret", SECRETS, ids=lambda secret: secret.setting)
def test_a_secret_that_is_set_is_not_read_from_its_parameter(secret: Secret, value: str) -> None:
    parameters = InMemoryParameterStore({PARAMETER: "https://value.example/ssm"})

    read = _setting(secret, {secret.variable: PARAMETER, secret.setting: value}, parameters=parameters)

    assert read == _setting(secret, {secret.setting: value})
    assert parameters.requested == []


@pytest.mark.parametrize("secret", OPTIONAL_SECRETS, ids=lambda secret: secret.setting)
def test_a_missing_optional_secret_reads_as_empty(secret: Secret) -> None:
    read = _setting(secret, {secret.variable: PARAMETER}, parameters=InMemoryParameterStore({}))

    assert read == _setting(secret, {secret.setting: ""})


@pytest.mark.parametrize("secret", REQUIRED_SECRETS, ids=lambda secret: secret.setting)
def test_a_missing_required_secret_is_a_configuration_error(secret: Secret) -> None:
    with pytest.raises(ConfigurationError) as rejected:
        Settings.from_environment(
            {secret.variable: PARAMETER}, parameters=InMemoryParameterStore({})
        )

    assert rejected.value.problems == (f"{secret.variable} names a parameter that does not exist",)


def test_the_database_url_and_the_marketaux_token_are_the_required_secrets() -> None:
    assert [secret.setting for secret in REQUIRED_SECRETS] == [
        "DATABASE_URL",
        "MARKETAUX_API_TOKEN",
    ]


def test_a_named_secret_needs_a_parameter_store() -> None:
    with pytest.raises(ConfigurationError) as rejected:
        Settings.from_environment({"BREVO_API_KEY_PARAMETER": PARAMETER})

    assert rejected.value.problems == (
        "BREVO_API_KEY_PARAMETER is set, but no parameter store was given",
    )


class FakeSsm:
    """An SSM client that answers every GetParameter the same way."""

    def __init__(self, error_code: str | None = None) -> None:
        self.error_code = error_code
        self.requests: list[dict[str, Any]] = []

    def get_parameter(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if self.error_code is not None:
            raise ClientError({"Error": {"Code": self.error_code}}, "GetParameter")
        return {"Parameter": {"Name": request["Name"], "Value": "decrypted"}}


def test_ssm_decrypts_the_parameter() -> None:
    client = FakeSsm()

    assert SsmParameterStore(client).get(PARAMETER) == "decrypted"
    assert client.requests == [{"Name": PARAMETER, "WithDecryption": True}]


def test_ssm_answers_none_for_a_missing_parameter() -> None:
    assert SsmParameterStore(FakeSsm("ParameterNotFound")).get(PARAMETER) is None


def test_ssm_raises_any_other_error() -> None:
    with pytest.raises(ClientError):
        SsmParameterStore(FakeSsm("AccessDeniedException")).get(PARAMETER)


def test_the_first_read_resolves_secrets_from_ssm(
    unbuilt_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ssm = InMemoryParameterStore({PARAMETER: "brevo-key-from-ssm"})
    monkeypatch.setattr(config, "SsmParameterStore", lambda: ssm)
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    monkeypatch.setenv("BREVO_API_KEY_PARAMETER", PARAMETER)

    assert settings.BREVO_API_KEY == "brevo-key-from-ssm"
    assert ssm.requested == [PARAMETER]
    assert "BREVO_API_KEY" not in os.environ


def test_no_repr_shows_a_value() -> None:
    built = Settings.from_environment(
        {
            "DATABASE_URL": "postgresql://app:hunter2@db.example/prod",
            "BREVO_API_KEY": "xkeysib-value",
        }
    )

    for shown in (repr(built), str(built), repr(settings), str(settings)):
        assert "hunter2" not in shown
        assert "xkeysib" not in shown
