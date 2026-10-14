"""The runtime configuration: every setting a backend process runs with.

Each setting is declared once, as a field of ``Settings`` named after its
environment variable, with its default and its limits. ``settings`` is built
from the environment the first time any setting is read, and the whole set is
checked then: a malformed value, or one outside its limits, raises
``ConfigurationError``, which names every bad variable and never its value.

A secret (``SECRETS``) is a setting AWS keeps in SSM Parameter Store. A
Lambda's environment holds only the parameter's name, in
``<SETTING>_PARAMETER``, and the build reads the value through a
``ParameterStore`` when the setting itself is not set. The value stays in the
settings and never goes into ``os.environ``.

Three rules follow from building on first use:

- Importing this module reads no setting, so any module may import
  ``settings`` at the top, in any order.
- Secrets are read at the first use, in whatever process uses them.
- Tests patch ``settings`` with ``patch.object`` or ``monkeypatch.setattr``
  and never set an environment variable for a setting: the first read keeps
  whatever the environment held then. A test of how a value is read builds
  its own ``Settings.from_environment``.

Only the standard library and ``app`` modules that need nothing else are
imported at the top, because the queue-wiring CI job imports this module with
just pytest and PyYAML installed. boto3 is imported when SSM is first read.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from app.alert_vocabulary import DEFAULT_ALERT_MIN_CONFIDENCE
from app.sources import SOURCES, scheduled_tickers


def _load_local_env() -> None:
    """Load backend/.env for local runs without overriding real env vars."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env()


class ConfigurationError(Exception):
    """The environment holds settings the backend cannot run with.

    It is deliberately not a ValueError, so no ``except ValueError`` can take
    it for a bad request. ``problems`` names each bad variable and the limit
    it broke, never the value, because a value may be a secret.
    """

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("Invalid runtime configuration: " + "; ".join(self.problems))


@dataclass(frozen=True)
class Secret:
    """A setting AWS keeps in SSM Parameter Store.

    A function in infra/template.yaml names the parameter in ``variable`` as
    ``${ParameterPathPrefix}/<parameter>``. A missing optional secret reads as
    empty, which switches off the feature that needs it.
    """

    setting: str
    parameter: str
    optional: bool = False

    @property
    def variable(self) -> str:
        return f"{self.setting}_PARAMETER"


SECRETS = (
    Secret("DATABASE_URL", "database-url"),
    Secret("BREVO_API_KEY", "brevo-api-key", optional=True),
    Secret("MARKETAUX_API_TOKEN", "marketaux-api-token"),
    Secret("REDDIT_CLIENT_ID", "reddit-client-id", optional=True),
    Secret("REDDIT_CLIENT_SECRET", "reddit-client-secret", optional=True),
    Secret("PUBLIC_DISCUSSION_FEED_URLS", "public-discussion-feed-urls", optional=True),
)


class ParameterStore(Protocol):
    """Where secrets are kept."""

    def get(self, name: str) -> str | None:
        """The parameter's decrypted value, or None when it does not exist."""


class SsmParameterStore:
    """SSM Parameter Store, through one boto3 client made at the first read."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def get(self, name: str) -> str | None:
        # Imported on use: the queue-wiring CI job has no boto3.
        from botocore.exceptions import ClientError

        if self._client is None:
            import boto3

            self._client = boto3.client("ssm")
        try:
            response = self._client.get_parameter(Name=name, WithDecryption=True)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ParameterNotFound":
                return None
            raise
        return response["Parameter"]["Value"]


@dataclass
class InMemoryParameterStore:
    """Parameters held in a dict, for tests. ``requested`` lists each name read."""

    values: dict[str, str]
    requested: list[str] = field(default_factory=list)

    def get(self, name: str) -> str | None:
        self.requested.append(name)
        return self.values.get(name)


def _with_secrets(
    environ: Mapping[str, str],
    parameters: ParameterStore | None,
) -> tuple[dict[str, str], list[str]]:
    """A copy of ``environ`` holding each secret read from its parameter, and the problems.

    A secret is read only when its variable names a parameter and the setting
    itself is not set, even to an empty value.
    """
    resolved = dict(environ)
    problems = []
    for secret in SECRETS:
        name = environ.get(secret.variable, "")
        if not name or secret.setting in environ:
            continue
        if parameters is None:
            problems.append(f"{secret.variable} is set, but no parameter store was given")
            continue
        value = parameters.get(name)
        if value is None and not secret.optional:
            problems.append(f"{secret.variable} names a parameter that does not exist")
            continue
        resolved[secret.setting] = value or ""
    return resolved, problems


# Reads one variable's text. It raises ValueError saying which limit the text
# breaks, without the text.
Parse = Callable[[str], Any]


@dataclass(frozen=True)
class Declaration:
    """How one setting is declared: its variable, its default and how it is read.

    The template rules in tests/test_queue_wiring.py check infra/template.yaml
    against these.
    """

    name: str
    default: Any
    parse: Parse
    aliases: tuple[str, ...] = ()


def _setting(default: Any, parse: Parse, *, aliases: Sequence[str] = ()) -> Any:
    metadata = {"parse": parse, "aliases": tuple(aliases)}
    if isinstance(default, list):
        return field(default_factory=lambda: list(default), metadata=metadata)
    return field(default=default, metadata=metadata)


def text(
    default: str = "",
    *,
    strip: bool = False,
    lower: bool = False,
    rstrip: str = "",
    choices: Sequence[str] = (),
    non_empty: bool = False,
    max_length: int | None = None,
    empty_means_default: bool = False,
    aliases: Sequence[str] = (),
) -> str:
    """A text setting. Each alias is read in turn when the variable is empty."""

    def parse(raw: str) -> str:
        value = raw.strip() if strip else raw
        value = value.lower() if lower else value
        value = value.rstrip(rstrip) if rstrip else value
        if empty_means_default and not value:
            return default
        if choices and value not in choices:
            raise ValueError(f"must be one of {', '.join(choices)}")
        if non_empty and not value:
            raise ValueError("must not be empty")
        if max_length is not None and len(value) > max_length:
            raise ValueError(f"must be at most {max_length} characters")
        return value

    return cast(str, _setting(default, parse, aliases=aliases))


def flag(default: bool = False) -> bool:
    """A switch: "true" in any case turns it on, anything else turns it off."""
    return cast(bool, _setting(default, lambda raw: raw.lower() == "true"))


def integer(default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    """A whole number within its limits."""

    def parse(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError:
            raise ValueError("must be a whole number") from None
        if minimum is not None and value < minimum:
            raise ValueError(f"must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"must be at most {maximum}")
        return value

    return cast(int, _setting(default, parse))


def fraction(default: float) -> float:
    """A number from 0 to 1."""

    def parse(raw: str) -> float:
        try:
            value = float(raw)
        except ValueError:
            raise ValueError("must be a number") from None
        if not 0 <= value <= 1:
            raise ValueError("must be from 0 to 1")
        return value

    return cast(float, _setting(default, parse))


def names(
    default: Sequence[str],
    *,
    case: Literal["upper", "lower", "keep"],
    keep_only: Sequence[str] | None = None,
) -> list[str]:
    """A comma-separated list. Each entry is trimmed and empty entries are dropped.

    With ``keep_only``, an entry outside it is dropped and the rest follow its order.
    """
    convert: Callable[[str], str] = {
        "upper": str.upper,
        "lower": str.lower,
        "keep": lambda entry: entry,
    }[case]

    def parse(raw: str) -> list[str]:
        entries = [convert(entry.strip()) for entry in raw.split(",") if entry.strip()]
        if keep_only is None:
            return entries
        return [name for name in keep_only if name in entries]

    return cast(list[str], _setting(list(default), parse))


def _raw(environ: Mapping[str, str], variables: Sequence[str]) -> str | None:
    """The first of ``variables`` that is set and not empty, or the first set.

    None when none of them is set, so the setting keeps its default.
    """
    present = [environ[variable] for variable in variables if variable in environ]
    if not present:
        return None
    return next((value for value in present if value.strip()), present[0])


@dataclass(repr=False, eq=False)
class Settings:
    """Every setting with its default and limits. Read them through ``settings``.

    ``repr`` is the plain object one, so no log line can show a value.
    """

    DATABASE_URL: str = text("postgresql://user:password@localhost:5432/spike")
    AWS_REGION: str = text("ap-southeast-2")
    AUTH_PROVIDER: str = text(
        "legacy", strip=True, lower=True, choices=("legacy", "dual", "cognito")
    )
    COGNITO_USER_POOL_ID: str = text(strip=True)
    COGNITO_APP_CLIENT_ID: str = text(strip=True)
    COGNITO_ISSUER: str = text(strip=True)
    COGNITO_JWKS_CACHE_SECONDS: int = integer(300)
    COGNITO_LINK_EXISTING_BY_EMAIL: bool = flag()
    DISCOVERY_QUEUE_URL: str = text()
    ANALYSIS_QUEUE_URL: str = text()
    NOTIFICATIONS_ENABLED: bool = flag()
    NOTIFICATIONS_DRY_RUN: bool = flag()
    ALERT_SENDER_EMAIL: str = text()
    ALERT_SENDER_NAME: str = text("Stocks In Hand")
    BREVO_API_KEY: str = text()
    BREVO_API_BASE_URL: str = text("https://api.brevo.com/v3")
    ALERT_DAILY_BUDGET: int = integer(180, minimum=0)
    ALERT_MAX_PER_INVESTOR_PER_RUN: int = integer(5, minimum=1)
    # The threshold the preferences page shows before an investor saves a rule.
    ALERT_DEFAULT_MIN_CONFIDENCE: float = fraction(float(DEFAULT_ALERT_MIN_CONFIDENCE))
    ALERT_CLAIM_STALE_MINUTES: int = integer(15, minimum=1)
    ALERT_VERIFICATION_TOKEN_TTL_HOURS: int = integer(24, minimum=1)
    FRONTEND_BASE_URL: str = text("http://localhost:3000")
    # The tickers an admin may scrape by hand.
    SUPPORTED_TICKERS: list[str] = names(tuple(SOURCES), case="upper")
    REDDIT_CLIENT_ID: str = text()
    REDDIT_CLIENT_SECRET: str = text()
    REDDIT_USER_AGENT: str = text("windows:stocks-in-hand:1.0.0 (read-only ASX market research)")
    BLUESKY_IDENTIFIER: str = text()
    BLUESKY_APP_PASSWORD: str = text()
    BLUESKY_SERVICE_URL: str = text("https://bsky.social", rstrip="/")
    BLUESKY_PUBLIC_API_URL: str = text("https://public.api.bsky.app", rstrip="/")
    PUBLIC_DISCUSSION_FEED_URLS: list[str] = names((), case="keep")
    LLM_PROVIDER: str = text("bedrock", strip=True, lower=True, choices=("bedrock", "groq"))
    GROQ_API_KEY: str = text()
    GROQ_MODEL: str = text("openai/gpt-oss-120b")
    BEDROCK_ENABLED: bool = flag()
    BEDROCK_MODEL_ID: str = text("openai.gpt-oss-120b-1:0", strip=True, non_empty=True)
    BEDROCK_SERVICE_TIER: str = text(
        "default", strip=True, lower=True, choices=("default", "flex", "priority")
    )
    BEDROCK_MAX_PROMPT_CHARS: int = integer(30000, minimum=1000)
    FINBERT_MODEL: str = text("/app/finbert")
    MARKETAUX_API_TOKEN: str = text(strip=True, aliases=("MARKETAUX_API_KEY",))
    MARKETAUX_BASE_URL: str = text("https://api.marketaux.com/v1")
    NEWS_FETCH_LIMIT: int = integer(10)
    CORS_ORIGINS: list[str] = names(("http://localhost:3000",), case="keep")
    SESSION_COOKIE_NAME: str = text("stonks_session")
    SESSION_EXPIRE_DAYS: int = integer(7)
    SESSION_COOKIE_SECURE: bool = flag()
    SESSION_COOKIE_SAMESITE: str = text("lax")
    # The tickers the weekly schedule scrapes, in catalogue order. A ticker
    # outside the catalogue is dropped.
    SCHEDULED_TICKERS: list[str] = names(
        scheduled_tickers(), case="upper", keep_only=tuple(SOURCES)
    )
    MARKETAUX_ENABLED: bool = flag()
    # News stories the weekly schedule asks Marketaux for, per ticker.
    MARKETAUX_PER_TICKER_LIMIT: int = integer(10, minimum=1, maximum=25)
    # The sources the public discussion schedule collects. An unknown source
    # is dropped.
    SCHEDULED_PUBLIC_DISCUSSION_SOURCES: list[str] = names(
        ("bluesky", "mastodon"), case="lower", keep_only=("reddit", "bluesky", "mastodon", "blog")
    )
    PUBLIC_DISCUSSION_PER_SOURCE_LIMIT: int = integer(10, minimum=1, maximum=25)
    # What the scheduled Reddit, Bluesky and Mastodon searches look for.
    PUBLIC_DISCUSSION_SEARCH_QUERY: str = text(
        "ASX", strip=True, max_length=100, empty_means_default=True
    )

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
        *,
        parameters: ParameterStore | None = None,
    ) -> Settings:
        """The settings ``environ`` holds, with its secrets read from ``parameters``.

        ``environ`` is only read. A variable that is set is read even when it
        is empty. Every bad value is reported in one ConfigurationError.
        """
        resolved, problems = _with_secrets(environ, parameters)
        values: dict[str, Any] = {}
        for declaration in declared_settings().values():
            raw = _raw(resolved, (declaration.name, *declaration.aliases))
            if raw is None:
                continue
            try:
                values[declaration.name] = declaration.parse(raw)
            except ValueError as error:
                problems.append(f"{declaration.name} {error}")
        built = cls(**values)
        problems.extend(built._sign_in_problems())
        if problems:
            raise ConfigurationError(problems)
        return built

    def required(self, name: str) -> str:
        """The value of a text setting the caller cannot work without."""
        value = getattr(self, name)
        if not value:
            raise ConfigurationError([f"{name} must be set"])
        return value

    def _sign_in_problems(self) -> list[str]:
        """Cognito sign-in needs its user pool, its app client and a JWKS cache."""
        if self.AUTH_PROVIDER not in {"dual", "cognito"}:
            return []
        when = f"when AUTH_PROVIDER is {self.AUTH_PROVIDER}"
        problems = [
            f"{name} must be set {when}"
            for name in ("COGNITO_USER_POOL_ID", "COGNITO_APP_CLIENT_ID")
            if not getattr(self, name)
        ]
        if self.COGNITO_JWKS_CACHE_SECONDS <= 0:
            problems.append(f"COGNITO_JWKS_CACHE_SECONDS must be greater than zero {when}")
        return problems


def declared_settings() -> dict[str, Declaration]:
    """Every setting's declaration by variable name, in declaration order."""
    return {
        setting.name: Declaration(
            name=setting.name,
            default=(
                setting.default
                if setting.default_factory is MISSING
                else setting.default_factory()
            ),
            parse=setting.metadata["parse"],
            aliases=setting.metadata["aliases"],
        )
        for setting in fields(Settings)
    }


_lock = threading.Lock()
_built: Settings | None = None


def get_settings() -> Settings:
    """This process's settings, built at the first call from its environment and SSM."""
    global _built
    built = _built
    if built is None:
        with _lock:
            built = _built
            if built is None:
                built = _built = Settings.from_environment(
                    os.environ, parameters=SsmParameterStore()
                )
    return built


def reset_settings() -> None:
    """Forget the built settings, so the next read builds them again. For tests."""
    global _built
    with _lock:
        _built = None


class _SettingsProxy:
    """Stands in for the built Settings, so importing this module builds nothing.

    Reading, setting or deleting an attribute builds the settings first, then
    acts on them, so ``patch.object(settings, ...)`` and
    ``monkeypatch.setattr(settings, ...)`` patch the real values.
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        return getattr(get_settings(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(get_settings(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(get_settings(), name)

    def __repr__(self) -> str:
        return "<settings, built from the environment at the first read>"


settings: Settings = cast(Settings, _SettingsProxy())
