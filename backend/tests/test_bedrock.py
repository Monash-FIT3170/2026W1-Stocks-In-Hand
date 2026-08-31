"""Contracts for bounded Amazon Bedrock inference."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi.routing import APIRoute

from app.api.deps import get_current_investor, require_admin_investor
from app.api.routes import category_sentiment, gemini, reddit
from app.services import bedrock, llm


def _response(
    content: str,
    *,
    input_tokens: int = 20,
    output_tokens: int = 10,
) -> dict[str, io.BytesIO]:
    return {
        "body": io.BytesIO(
            json.dumps(
                {
                    "choices": [{"message": {"content": content}}],
                    "usage": {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                    },
                }
            ).encode("utf-8")
        )
    }


def test_invoke_text_uses_bounded_gpt_oss_request() -> None:
    """Bedrock requests must use the approved model and output bounds."""
    client = MagicMock()
    client.invoke_model.return_value = _response(
        '<reasoning>internal analysis</reasoning>\n{"summary": "Bounded output"}'
    )

    with patch.object(bedrock.settings, "BEDROCK_ENABLED", True), patch.object(
        bedrock.settings,
        "BEDROCK_MODEL_ID",
        "openai.gpt-oss-120b-1:0",
    ), patch.object(
        bedrock.settings,
        "BEDROCK_SERVICE_TIER",
        "flex",
    ), patch.object(
        bedrock.settings,
        "BEDROCK_MAX_PROMPT_CHARS",
        30000,
    ), patch.object(
        bedrock.settings,
        "BEDROCK_MAX_OUTPUT_TOKENS",
        1024,
    ), patch.object(
        bedrock,
        "_client",
        return_value=client,
    ):
        result = bedrock.invoke_text("Summarise this filing.")

    assert result == '{"summary": "Bounded output"}'
    request = client.invoke_model.call_args.kwargs
    assert request["modelId"] == "openai.gpt-oss-120b-1:0"
    assert request["accept"] == "application/json"
    assert request["contentType"] == "application/json"
    payload = json.loads(request["body"])
    assert payload == {
        "model": "openai.gpt-oss-120b-1:0",
        "messages": [{"role": "user", "content": "Summarise this filing."}],
        "max_completion_tokens": 1024,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "service_tier": "flex",
        "stream": False,
    }


def test_invoke_text_rejects_disabled_bedrock() -> None:
    """The feature gate must block calls before an AWS client is used."""
    with patch.object(bedrock.settings, "BEDROCK_ENABLED", False), pytest.raises(
        RuntimeError,
        match="disabled",
    ):
        bedrock.invoke_text("Prompt")


def test_invoke_text_rejects_prompt_over_configured_limit() -> None:
    """Prompts over the configured cap must fail before invocation."""
    with patch.object(bedrock.settings, "BEDROCK_ENABLED", True), patch.object(
        bedrock.settings,
        "BEDROCK_MAX_PROMPT_CHARS",
        10,
    ), pytest.raises(ValueError, match="character limit"):
        bedrock.invoke_text("x" * 11)


def test_invoke_text_sanitises_aws_client_errors() -> None:
    """AWS error details must not escape through the service boundary."""
    client = MagicMock()
    client.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "sensitive detail"}},
        "InvokeModel",
    )
    with patch.object(bedrock.settings, "BEDROCK_ENABLED", True), patch.object(
        bedrock.settings,
        "BEDROCK_MAX_PROMPT_CHARS",
        30000,
    ), patch.object(
        bedrock,
        "_client",
        return_value=client,
    ), pytest.raises(RuntimeError) as error:
        bedrock.invoke_text("Prompt")

    assert str(error.value) == "Amazon Bedrock model invocation failed"
    assert "sensitive detail" not in str(error.value)


def test_provider_routes_structured_category_request_to_bedrock() -> None:
    """The default provider route must dispatch category work to Bedrock."""
    response = json.dumps(
        {
            "revenue": "Revenue increased.",
            "strategy": "",
            "risk": "",
            "dividend": "",
            "organisational": "",
        }
    )
    with patch.object(llm.settings, "LLM_PROVIDER", "bedrock"), patch.object(
        llm.settings,
        "BEDROCK_MODEL_ID",
        "openai.gpt-oss-120b-1:0",
    ), patch.object(
        llm.bedrock,
        "invoke_text",
        return_value=response,
    ) as invoke:
        result = llm.categorise_chunk("Revenue increased during the half year.")

    assert result["revenue"] == "Revenue increased."
    assert llm.active_model_name() == "bedrock:openai.gpt-oss-120b-1:0"
    invoke.assert_called_once()


def test_announcement_summary_repairs_malformed_model_json_once() -> None:
    """A formatting defect must not discard otherwise recoverable analysis."""
    malformed = '{\nsummary: "An update"\n}'
    repaired = json.dumps(
        {
            "summary": "The company announced an update.",
            "about": "The filing describes the update.",
            "changed": "The update was confirmed.",
            "matters": "Investors can assess the confirmed change.",
            "confirmed_facts": ["The company confirmed the update."],
            "speculation": [],
        }
    )

    with patch.object(
        llm,
        "_call_llm",
        side_effect=[malformed, repaired],
    ) as invoke:
        result = llm.summarise_announcement(
            title="Company update",
            category="organisational",
            extracted_data={},
            raw_text="The company confirmed an update.",
        )

    assert result["summary"] == "The company announced an update."
    assert invoke.call_count == 2
    repair_prompt = invoke.call_args_list[1].args[0]
    assert json.dumps(malformed, ensure_ascii=False) in repair_prompt
    assert invoke.call_args_list[1].kwargs == {"temperature": 0}


def test_announcement_summary_does_not_repair_valid_json() -> None:
    """Valid structured output must retain the single-call fast path."""
    response = json.dumps(
        {
            "summary": "The company announced an update.",
            "about": "The filing describes the update.",
            "changed": "The update was confirmed.",
            "matters": "Investors can assess the confirmed change.",
            "confirmed_facts": ["The company confirmed the update."],
            "speculation": [],
        }
    )

    with patch.object(llm, "_call_llm", return_value=response) as invoke:
        llm.summarise_announcement(
            title="Company update",
            category="organisational",
            extracted_data={},
            raw_text="The company confirmed an update.",
        )

    invoke.assert_called_once()


def test_reddit_digest_rejects_unrecognised_sentiment() -> None:
    """Reddit digests must use one of the supported sentiment labels."""
    with pytest.raises(ValueError, match="sentiment was not recognised"):
        llm.parse_reddit_digest_response(
            '{"summary":"A summary","dominant_sentiment":"excited",'
            '"key_themes":[]}'
        )


@pytest.mark.parametrize(
    "path",
    [
        "/gemini/categorise/recent",
        "/gemini/summarise/ticker/{symbol}",
        "/gemini/summarise/artifact/{artifact_id}",
    ],
)
def test_cost_bearing_generation_routes_require_admin(path: str) -> None:
    """Manual generation routes must require an admin investor."""
    route = next(
        route
        for route in gemini.router.routes
        if isinstance(route, APIRoute) and route.path == path
    )

    assert require_admin_investor in {
        dependency.call for dependency in route.dependant.dependencies
    }


def test_reddit_digest_route_requires_an_investor() -> None:
    """Manual Reddit digest generation must require an authenticated investor."""
    route = next(
        route
        for route in reddit.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/reddit/ticker-sentiment/{ticker_symbol}"
    )

    assert get_current_investor in {
        dependency.call for dependency in route.dependant.dependencies
    }


def test_sentiment_generation_route_requires_admin() -> None:
    """The compatibility sentiment POST must protect its Bedrock calls."""
    route = next(
        route
        for route in category_sentiment.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/sentiment/{ticker}"
        and "POST" in route.methods
    )

    assert require_admin_investor in {
        dependency.call for dependency in route.dependant.dependencies
    }
