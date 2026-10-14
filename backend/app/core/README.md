# Core Implementation

The `core` folder holds the runtime configuration: every setting a backend
process runs with.

## Files

`config.py`

Declares the `Settings` dataclass and the shared `settings` object.

## How Configuration Works

Each setting is declared once, as a field of `Settings` named after its
environment variable, with its default and its limits:

```python
ALERT_DAILY_BUDGET: int = integer(180, minimum=0)
AUTH_PROVIDER: str = text("legacy", strip=True, lower=True, choices=("legacy", "dual", "cognito"))
```

The declaration helpers are `text`, `flag`, `integer`, `fraction` and
`names` (a comma-separated list).

`settings` is built the first time any setting is read, not when the module
is imported:

1. A variable that is set is read, even when it is empty.
2. A variable that is not set keeps the declared default.
3. The whole set is checked at that first read. A malformed value, or one
   outside its limits, raises `ConfigurationError`. The error names every bad
   variable and the limit it broke, never the value.

`ConfigurationError` is not a `ValueError`, so a route's `except ValueError`
cannot turn a broken deployment into a 400.

For local runs, importing `config.py` loads `backend/.env` into the
environment without overriding variables that are already set. Docker
compose files set their own values, such as `DATABASE_URL`, so containers
connect to their own services instead of `localhost`.

## Secrets

`SECRETS` lists the settings AWS keeps in SSM Parameter Store, such as
`DATABASE_URL` and `BREVO_API_KEY`. In AWS a Lambda's environment holds only
the parameter's name, in `<SETTING>_PARAMETER`. When that variable names a
parameter and the setting itself is not set, the first read gets the value
through `SsmParameterStore`, in whatever process makes it. The value stays in
`settings` and is never copied into `os.environ`.

A secret registered with `may_be_missing=True`, such as the Reddit
credentials, reads as empty when its parameter does not exist, which switches
its feature off. For `DATABASE_URL` and `MARKETAUX_API_TOKEN` a missing
parameter is a `ConfigurationError`. That is separate from whether a secret is
gated, read only while a stack switch is on: the Marketaux token is gated but
must exist whenever its variable names it. Tests use
`InMemoryParameterStore`. `tests/test_queue_wiring.py` checks that every
`*_PARAMETER` variable in `infra/template.yaml` names a registered secret's
parameter.

## Where It Is Used

Modules import the shared object and read it where they need a value:

```python
from app.core.config import settings

settings.DATABASE_URL
```

A few modules read a setting when they are imported, such as
`app/database/connection.py` (`DATABASE_URL`) and `main.py`
(`CORS_ORIGINS`). That builds the settings at that point.

## Tests

Patch `settings` with `patch.object` or `monkeypatch.setattr`. Do not set an
environment variable for a setting: the first read keeps whatever the
environment held then, so the value would leak into later tests. A test of
how a value is read calls `Settings.from_environment({...})`, as
`tests/test_runtime_configuration.py` does.

## When To Add More Settings

Declare a new value here when it is configuration, such as a URL, a key, a
model name, a limit or a feature switch. Give it its limits in the
declaration, so a bad value fails at the first read instead of where it is
used, and read it through `settings`, never with `os.getenv`.

Two tests hold this:

- `tests/test_runtime_configuration.py` fails when other runtime code reads
  the environment. Only facts AWS sets about the process, such as
  `AWS_LAMBDA_FUNCTION_NAME`, are allowed.
- `tests/test_queue_wiring.py` fails when a function in
  `infra/template.yaml` sets a variable that is not declared here, a literal
  that differs from its declared default, or a parameter whose allowed
  values the setting would refuse.
