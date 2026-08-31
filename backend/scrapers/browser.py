"""Shared Chromium launch settings for local and Lambda scrapers."""

from __future__ import annotations

import os
import posixpath
from collections.abc import Sequence
from typing import Any


_CHROMIUM_ARGS = (
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-zygote",
)
# Lambda container images expose /tmp as their only writable filesystem path.
_LAMBDA_TMP = "/tmp"  # nosec B108


def chromium_launch_options(
    *,
    extra_args: Sequence[str] = (),
) -> dict[str, Any]:
    """Return one consistent, Lambda-safe set of Playwright launch options.

    Lambda container images have a read-only root filesystem. Chromium also
    tries to initialise GPU and user cache processes before the first page is
    created. Give those processes writable locations and disable the unusable
    GPU hardware path and unsupported zygote credential sandbox so a browser
    cannot launch successfully and then immediately die. Chromium's software
    renderer remains enabled because headless mode needs it in Lambda.
    """
    options: dict[str, Any] = {
        "headless": True,
        "args": list(dict.fromkeys((*_CHROMIUM_ARGS, *extra_args))),
    }
    if os.getenv("AWS_LAMBDA_RUNTIME_API"):
        options["env"] = {
            **os.environ,
            "HOME": _LAMBDA_TMP,
            "TMPDIR": _LAMBDA_TMP,
            "XDG_CACHE_HOME": posixpath.join(_LAMBDA_TMP, ".cache"),
            "XDG_CONFIG_HOME": posixpath.join(_LAMBDA_TMP, ".config"),
        }
    return options
