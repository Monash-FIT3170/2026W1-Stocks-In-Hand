import argparse
import sys
import time

import httpx


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Poll a health endpoint until it reports healthy or a deadline passes.",
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Health endpoint to poll, e.g. https://staging.example.com/api/health",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="Total time to keep retrying before giving up. Default 180s to survive a cold Lambda start.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=10,
        help="Time to wait between attempts.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=5.0,
        help="Timeout for a single HTTP request.",
    )
    return parser


def wait_for_health(
    url: str,
    timeout_seconds: int,
    interval_seconds: int,
    request_timeout_seconds: float,
) -> bool:
    """Poll ``url`` until it returns HTTP 200 or ``timeout_seconds`` elapses."""
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            response = httpx.get(url, timeout=request_timeout_seconds)
            if response.status_code == 200:
                print(f"Attempt {attempt}: {url} is healthy (200)")
                return True
            print(f"Attempt {attempt}: {url} returned {response.status_code}")
        except httpx.RequestError as exc:
            print(f"Attempt {attempt}: {url} was unreachable ({exc})")

        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_seconds)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    healthy = wait_for_health(
        args.url,
        timeout_seconds=args.timeout_seconds,
        interval_seconds=args.interval_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
    )
    if healthy:
        return 0
    print(
        f"{args.url} did not become healthy within {args.timeout_seconds}s",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
