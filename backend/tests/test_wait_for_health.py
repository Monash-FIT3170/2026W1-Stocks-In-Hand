import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from scripts.wait_for_health import wait_for_health


def test_wait_for_health_returns_true_on_first_success() -> None:
    response = MagicMock(status_code=200)
    with patch("scripts.wait_for_health.httpx.get", return_value=response) as get:
        assert wait_for_health(
            "https://example.com/health",
            timeout_seconds=30,
            interval_seconds=10,
            request_timeout_seconds=5.0,
        )
    get.assert_called_once()


def test_wait_for_health_retries_then_succeeds() -> None:
    unhealthy = MagicMock(status_code=503)
    healthy = MagicMock(status_code=200)
    with patch(
        "scripts.wait_for_health.httpx.get", side_effect=[unhealthy, healthy]
    ), patch("scripts.wait_for_health.time.sleep") as sleep, patch(
        "scripts.wait_for_health.time.monotonic", side_effect=[0, 0, 0, 0]
    ):
        assert wait_for_health(
            "https://example.com/health",
            timeout_seconds=30,
            interval_seconds=10,
            request_timeout_seconds=5.0,
        )
    sleep.assert_called_once_with(10)


def test_wait_for_health_gives_up_after_deadline() -> None:
    unhealthy = MagicMock(status_code=503)
    with patch(
        "scripts.wait_for_health.httpx.get", return_value=unhealthy
    ), patch("scripts.wait_for_health.time.sleep"), patch(
        "scripts.wait_for_health.time.monotonic", side_effect=[0, 5, 40]
    ):
        assert not wait_for_health(
            "https://example.com/health",
            timeout_seconds=30,
            interval_seconds=10,
            request_timeout_seconds=5.0,
        )


def test_wait_for_health_treats_connection_error_as_unhealthy() -> None:
    with patch(
        "scripts.wait_for_health.httpx.get",
        side_effect=httpx.ConnectError("connection refused"),
    ), patch("scripts.wait_for_health.time.sleep"), patch(
        "scripts.wait_for_health.time.monotonic", side_effect=[0, 40]
    ):
        assert not wait_for_health(
            "https://example.com/health",
            timeout_seconds=30,
            interval_seconds=10,
            request_timeout_seconds=5.0,
        )
