"""Regression tests for security-critical Cognito template settings."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class CloudFormationLoader(yaml.SafeLoader):
    """Load CloudFormation YAML while preserving intrinsic values as data."""


def _construct_intrinsic(loader, _tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CloudFormationLoader.add_multi_constructor("!", _construct_intrinsic)


def _template() -> dict:
    return yaml.load(
        (ROOT / "infra" / "template.yaml").read_text(encoding="utf-8"),
        Loader=CloudFormationLoader,
    )


def test_cognito_browser_client_has_no_secret() -> None:
    properties = _template()["Resources"]["CognitoUserPoolClient"]["Properties"]

    assert properties["GenerateSecret"] is False


def test_cognito_user_pool_is_retained_and_supports_totp() -> None:
    resource = _template()["Resources"]["CognitoUserPool"]

    assert resource["DeletionPolicy"] == "Retain"
    assert resource["UpdateReplacePolicy"] == "Retain"
    assert resource["Properties"]["DeletionProtection"] == "ACTIVE"
    assert resource["Properties"]["MfaConfiguration"] == "OPTIONAL"
    assert resource["Properties"]["EnabledMfas"] == ["SOFTWARE_TOKEN_MFA"]


def test_authentication_modes_keep_an_explicit_transition_state() -> None:
    parameter = _template()["Parameters"]["AuthProvider"]

    assert parameter["Default"] == "legacy"
    assert parameter["AllowedValues"] == ["legacy", "dual", "cognito"]


def test_gateway_authorizer_is_defined_without_blocking_public_proxy() -> None:
    api_properties = _template()["Resources"]["ServerlessHttpApi"]["Properties"]

    assert "CognitoJwtAuthorizer" in api_properties["Auth"]["Authorizers"]
    assert "DefaultAuthorizer" not in api_properties["Auth"]
