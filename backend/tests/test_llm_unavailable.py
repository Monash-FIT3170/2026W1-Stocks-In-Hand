"""A provider that is switched off raises one typed error.

Before this was typed, the fallback string-matched "not configured", which only
the Groq adapter raised. The news summary service still turns ``Unavailable``
back into this error, and its callers count it among their errors.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.llm_errors import LLMUnavailableError


def test_typed_error_stays_a_runtime_error_for_existing_route_handlers() -> None:
    assert issubclass(LLMUnavailableError, RuntimeError)
