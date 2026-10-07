"""Document size limits agree between the code and the deployed template.

The download and analysis workers defaulted to 10 MiB while the template set
25 MiB, and the DOCX expansion limit defaulted to 50 MiB in code against
20 MiB in the template, so a local run and a Lambda missing the variable
enforced different limits.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lambdas import download_validation as limits

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _configured(name: str) -> set[int]:
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(encoding="utf-8")
    return {int(value) for value in re.findall(rf'{name}: "(\d+)"', template)}


def test_template_limits_match_the_code_defaults() -> None:
    assert _configured("MAX_DOCUMENT_BYTES") == {limits.DEFAULT_MAX_DOCUMENT_BYTES}
    assert _configured("MAX_DOCX_UNCOMPRESSED_BYTES") == {
        limits.DEFAULT_MAX_DOCX_UNCOMPRESSED_BYTES
    }


def test_workers_fall_back_to_the_deployed_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_DOCUMENT_BYTES", raising=False)
    monkeypatch.delenv("MAX_DOCX_UNCOMPRESSED_BYTES", raising=False)

    assert limits.document_size_limit() == 25 * 1024 * 1024
    assert limits.docx_uncompressed_limit() == 20 * 1024 * 1024


def test_environment_still_overrides_the_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_DOCUMENT_BYTES", "1024")
    monkeypatch.setenv("MAX_DOCX_UNCOMPRESSED_BYTES", "2048")

    assert limits.document_size_limit() == 1024
    assert limits.docx_uncompressed_limit() == 2048


def test_no_worker_hard_codes_its_own_default() -> None:
    lambdas = REPOSITORY_ROOT / "backend" / "lambdas"
    offenders = [
        path.name
        for path in lambdas.glob("*.py")
        if re.search(r'getenv\("MAX_(DOCUMENT|DOCX_UNCOMPRESSED)_BYTES", "\d+"\)', path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
