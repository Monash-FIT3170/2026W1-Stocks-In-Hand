import asyncio
import json
from types import SimpleNamespace

from lambda_api import handler


def test_api_gateway_base_path_routes_health() -> None:
    event = {
        "version": "2.0",
        "routeKey": "GET /api/health",
        "rawPath": "/api/health",
        "rawQueryString": "",
        "headers": {
            "host": "demo.cloudfront.net",
            "x-forwarded-proto": "https",
        },
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "api-id",
            "domainName": "api-id.execute-api.ap-southeast-2.amazonaws.com",
            "domainPrefix": "api-id",
            "http": {
                "method": "GET",
                "path": "/api/health",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "pytest",
            },
            "requestId": "request-id",
            "routeKey": "GET /api/health",
            "stage": "$default",
            "time": "03/Aug/2026:00:00:00 +0000",
            "timeEpoch": 1785715200000,
        },
        "isBase64Encoded": False,
    }
    context = SimpleNamespace(
        function_name="stocks-in-hand-staging-api",
        function_version="$LATEST",
        invoked_function_arn=(
            "arn:aws:lambda:ap-southeast-2:123456789012:"
            "function:stocks-in-hand-staging-api"
        ),
        memory_limit_in_mb="1024",
        aws_request_id="request-id",
        log_group_name="/aws/lambda/stocks-in-hand-staging-api",
        log_stream_name="test",
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        response = handler(event, context)
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}
