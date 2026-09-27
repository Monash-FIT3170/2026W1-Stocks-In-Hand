"""Parse infra/template.yaml as data for contract tests.

Text slices of the template depend on resource order and can match a value
from the next resource, so assertions about a single parameter or resource
should read it from this parsed form instead.
"""

from functools import lru_cache
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class CloudFormationLoader(yaml.SafeLoader):
    """Load CloudFormation YAML while preserving intrinsic values as data."""


def _construct_intrinsic(loader, _tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CloudFormationLoader.add_multi_constructor("!", _construct_intrinsic)


@lru_cache(maxsize=None)
def load_template(relative_path: str = "infra/template.yaml") -> dict:
    return yaml.load(
        (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8"),
        Loader=CloudFormationLoader,
    )


def template_parameters() -> dict:
    return load_template()["Parameters"]


def image_functions() -> list[str]:
    """Logical IDs of every Lambda deployed from a container image."""
    return sorted(
        name
        for name, resource in load_template()["Resources"].items()
        if resource.get("Type") == "AWS::Serverless::Function"
        and resource.get("Properties", {}).get("PackageType") == "Image"
    )
