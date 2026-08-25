from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_api_image_does_not_own_finbert_inference() -> None:
    dockerfile = (REPOSITORY_ROOT / "backend" / "Dockerfile.api").read_text(encoding="utf-8")
    route = (
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "api"
        / "routes"
        / "category_sentiment.py"
    ).read_text(encoding="utf-8")

    assert "requirements-analysis.txt" not in dockerfile
    assert "transformers" not in dockerfile
    assert '@router.get("/{ticker}"' in route
    assert "return read_ticker_category_sentiment(" in route
    assert "On-demand FinBERT inference is not available in the API runtime" in route


def test_cloudfront_routes_unknown_pages_to_exported_404() -> None:
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(encoding="utf-8")

    assert "request.uri = '/404.html'" in template
    assert "x-stonks-not-found" in template
    assert "response.statusCode = 404" in template
    assert "EventType: viewer-response" in template


def test_legacy_release_retains_cognito_foundation() -> None:
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(encoding="utf-8")

    user_pool = template.split("  CognitoUserPool:", 1)[1].split(
        "  CognitoUserPoolClient:", 1
    )[0]
    app_client = template.split("  CognitoUserPoolClient:", 1)[1].split(
        "  ServerlessHttpApi:", 1
    )[0]

    assert "Type: AWS::Cognito::UserPool" in user_pool
    assert "DeletionPolicy: Retain" in user_pool
    assert "UpdateReplacePolicy: Retain" in user_pool
    assert "DeletionProtection: ACTIVE" in user_pool

    assert "Type: AWS::Cognito::UserPoolClient" in app_client
    assert "DeletionPolicy: Retain" in app_client
    assert "UpdateReplacePolicy: Retain" in app_client
    assert "GenerateSecret: false" in app_client
    assert "CognitoUserPoolId:" in template
    assert "CognitoUserPoolClientId:" in template


def test_frontend_uses_read_only_sentiment_contract() -> None:
    api = (
        REPOSITORY_ROOT / "frontend" / "src" / "app" / "lib" / "api.js"
    ).read_text(encoding="utf-8")

    sentiment_function = api.split("export async function fetchTickerCategorySentiment", 1)[1]
    assert "fetchJsonCoalesced" in sentiment_function
    assert 'method: "POST"' not in sentiment_function.split("}", 1)[0]
    assert "persist=false" not in sentiment_function
