"""Access policy for state-changing and cost-bearing API routes.

Every route that is not a plain read must name an authentication dependency.
The only exceptions are the routes that exist to establish or end an identity,
or that authenticate with a signed token in the request body instead.
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from app.api.deps import (
    get_cognito_principal,
    get_current_investor,
    require_admin_investor,
)
from app.database.connection import get_db
from app.schemas.information_platform import InformationPlatformUpdate
from app.schemas.ticker import TickerUpdate

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
AUTH_DEPENDENCIES = {
    get_cognito_principal,
    get_current_investor,
    require_admin_investor,
}
# Routes that must stay reachable without a session.
PUBLIC_WRITE_ROUTES = {
    ("POST", "/auth/sign-up"),
    ("POST", "/auth/sign-in"),
    ("POST", "/auth/sign-out"),
    ("POST", "/notifications/verify"),
    ("POST", "/notifications/unsubscribe"),
}


def _dependency_calls(dependant) -> set:
    calls = set()
    for dependency in dependant.dependencies:
        calls.add(dependency.call)
        calls |= _dependency_calls(dependency)
    return calls


def _api_routes(routes, prefix: str = "", inherited: frozenset = frozenset()):
    """Yield (path, route, include-level dependency calls) for every API route.

    Newer FastAPI versions keep included routers nested instead of copying their
    routes onto the app, so walk them and carry the include prefix and any
    ``include_router(dependencies=...)`` along.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route, inherited
            continue
        context = getattr(route, "include_context", None)
        router = getattr(route, "original_router", None)
        if context is not None and router is not None:
            yield from _api_routes(
                router.routes,
                prefix + context.prefix,
                inherited | {dependency.dependency for dependency in context.dependencies},
            )


def _write_routes() -> list[tuple[str, str, set]]:
    return [
        (method, path, _dependency_calls(route.dependant) | inherited)
        for path, route, inherited in _api_routes(main.app.routes)
        for method in sorted(route.methods - READ_METHODS)
    ]


def test_every_write_route_requires_authentication() -> None:
    unprotected = [
        f"{method} {path}"
        for method, path, dependency_calls in _write_routes()
        if (method, path) not in PUBLIC_WRITE_ROUTES
        and not dependency_calls & AUTH_DEPENDENCIES
    ]

    assert unprotected == []


def test_sweep_sees_included_router_routes() -> None:
    write_routes = {(method, path) for method, path, _calls in _write_routes()}

    assert ("POST", "/news/fetch/{symbol}") in write_routes
    assert ("PATCH", "/tickers/{ticker_id}") in write_routes


def test_public_write_allowlist_names_real_routes() -> None:
    write_routes = {(method, path) for method, path, _calls in _write_routes()}

    assert PUBLIC_WRITE_ROUTES <= write_routes


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/news/fetch/BHP"),
        ("POST", "/news/summarise/BHP"),
        ("POST", "/news/sentiment/BHP"),
        ("POST", "/artifacts/"),
        ("POST", "/artifact-sentiments/"),
        ("POST", "/artifact-summaries/"),
        ("POST", "/information-platforms/"),
        ("PATCH", f"/information-platforms/{uuid.uuid4()}"),
        ("POST", "/tickers/"),
        ("PATCH", f"/tickers/{uuid.uuid4()}"),
        ("POST", "/analyse"),
    ],
)
def test_anonymous_writes_are_rejected_before_any_work(method: str, path: str) -> None:
    main.app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        with patch.object(main.settings, "AUTH_PROVIDER", "legacy"), patch(
            "app.services.marketaux.fetch_and_store_news"
        ) as fetch_news:
            response = TestClient(main.app).request(method, path, json={})
    finally:
        main.app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 401
    fetch_news.assert_not_called()


def test_ticker_update_accepts_only_descriptive_fields() -> None:
    assert TickerUpdate(sector="Energy").model_dump(exclude_unset=True) == {
        "sector": "Energy"
    }
    for payload in ({"symbol": "XYZ"}, {"id": str(uuid.uuid4())}, {"company_name": None}):
        with pytest.raises(ValidationError):
            TickerUpdate(**payload)


def test_platform_update_rejects_unknown_and_identity_fields() -> None:
    assert InformationPlatformUpdate(scrape_enabled=False).model_dump(
        exclude_unset=True
    ) == {"scrape_enabled": False}
    for payload in ({"name": "renamed"}, {"created_at": "2026-01-01"}, {"platform_type": None}):
        with pytest.raises(ValidationError):
            InformationPlatformUpdate(**payload)
