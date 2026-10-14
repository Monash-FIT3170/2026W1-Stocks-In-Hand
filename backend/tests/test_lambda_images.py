"""Every Lambda image ships the backend modules its handler imports.

Each Dockerfile copies an explicit list of files. The analysis image copied
``parsing/analysis.py`` but not the ``parsing.classification`` package,
``parsing.extractors`` or ``parsing.classification_metadata`` it imports, so
the analysis handler could not be imported once deployed. Nothing failed until
the Lambda started, because the image build never imports the handler.

The API image installs no model runtime: it reads the sentiment the analysis
worker stored and never runs FinBERT, so neither torch nor transformers is
installed in it, and every handler it runs starts without them.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools.template_model import template_model

BACKEND = Path(__file__).resolve().parents[1]

# The deploy workflow builds each image URI parameter from one Dockerfile.
IMAGE_DOCKERFILES = {
    "ApiImageUri": "Dockerfile.api",
    "ScraperImageUri": "Dockerfile.scraper",
    "AnalysisImageUri": "Dockerfile.analysis",
}
MODEL_RUNTIME = {"torch", "transformers"}
# pip options followed by a value that is not a requirement.
_PIP_VALUE_OPTIONS = {
    "-c",
    "--constraint",
    "-i",
    "--index-url",
    "--extra-index-url",
    "-f",
    "--find-links",
    "-t",
    "--target",
}


def _copied_paths(dockerfile: str) -> list[str]:
    """Build-context paths the Dockerfile copies into the image."""
    text = (BACKEND / dockerfile).read_text(encoding="utf-8").replace("\\\n", " ")
    copied: list[str] = []
    for line in text.splitlines():
        words = line.split()
        if not words or words[0] != "COPY":
            continue
        if any(word.startswith("--from") for word in words):
            continue
        copied.extend(word for word in words[1:-1] if not word.startswith("--"))
    return copied


def _module_file(name: str) -> Path | None:
    path = BACKEND.joinpath(*name.split("."))
    for candidate in (path.with_suffix(".py"), path / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _imported_names(tree: ast.AST, package: str) -> list[str]:
    """Every module an import statement may load, including function-level ones."""
    names: list[str] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for child in node.orelse:
                visit(child)
            return
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                parts = parts[: len(parts) - node.level + 1]
                base = ".".join([*parts, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            names.append(base)
            names.extend(f"{base}.{alias.name}" for alias in node.names)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return names


def _backend_imports(handler_module: str) -> set[str]:
    """Backend files a handler module loads, directly or through other modules."""
    files: dict[str, Path] = {}
    pending = [handler_module]
    while pending:
        parts = pending.pop().split(".")
        for end in range(1, len(parts) + 1):
            name = ".".join(parts[:end])
            if name in files or (path := _module_file(name)) is None:
                continue
            files[name] = path
            package = name if path.name == "__init__.py" else name.rpartition(".")[0]
            tree = ast.parse(path.read_text(encoding="utf-8"))
            pending.extend(_imported_names(tree, package))
    return {path.relative_to(BACKEND).as_posix() for path in files.values()}


def _image_handlers() -> list[tuple[str, str, str]]:
    handlers = []
    for logical_id, function in template_model().functions().items():
        properties = function.properties
        if properties.get("PackageType") != "Image":
            continue
        dockerfile = IMAGE_DOCKERFILES[properties["ImageUri"]["Ref"]]
        [command] = properties["ImageConfig"]["Command"]
        handlers.append((logical_id, dockerfile, command.rpartition(".")[0]))
    return sorted(handlers)


@pytest.mark.parametrize(
    ("dockerfile", "handler_module"),
    [(dockerfile, module) for _id, dockerfile, module in _image_handlers()],
    ids=[logical_id for logical_id, _dockerfile, _module in _image_handlers()],
)
def test_image_ships_every_backend_module_its_handler_imports(
    dockerfile: str,
    handler_module: str,
) -> None:
    copied = [path.rstrip("/") for path in _copied_paths(dockerfile)]

    missing = sorted(
        path
        for path in _backend_imports(handler_module)
        if not any(path == source or path.startswith(f"{source}/") for source in copied)
    )

    assert not missing, f"{dockerfile} does not copy: {missing}"


@pytest.mark.parametrize("dockerfile", sorted(set(IMAGE_DOCKERFILES.values())))
def test_image_copies_only_files_that_exist(dockerfile: str) -> None:
    missing = [
        source
        for source in _copied_paths(dockerfile)
        if not (BACKEND / source).exists()
    ]

    assert not missing, f"{dockerfile} copies missing paths: {missing}"


def test_import_scan_sees_function_level_and_relative_imports() -> None:
    """The check sees imports a handler only makes when a message arrives."""
    tree = ast.parse(
        "from typing import TYPE_CHECKING\n"
        "from .engine import classify\n"
        "if TYPE_CHECKING:\n"
        "    from scrapers.base import Announcement\n"
        "def handler():\n"
        "    from app.crud import artifact\n"
    )

    names = _imported_names(tree, "parsing.classification")

    assert "parsing.classification.engine" in names
    assert "app.crud.artifact" in names
    assert not any(name.startswith("scrapers") for name in names)
    assert "parsing/classification/engine.py" in _backend_imports("lambdas.analysis")


def _distribution(requirement: str) -> str:
    """The normalised distribution name of a requirement such as ``Foo_Bar[x]==1``."""
    name = re.split(r"[\s\[<>=!~;@]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements_file(path: Path) -> set[str]:
    """Distributions a requirements file names, following its ``-r`` files."""
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith(("-r ", "--requirement ")):
            names |= _requirements_file(path.parent / line.split(maxsplit=1)[1])
        elif line and not line.startswith("-"):
            names.add(_distribution(line))
    return names


def _installed_distributions(dockerfile: str) -> set[str]:
    """Distributions the Dockerfile's ``pip install`` commands name, with their ``-r`` files."""
    text = (BACKEND / dockerfile).read_text(encoding="utf-8").replace("\\\n", " ")
    names: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("RUN "):
            continue
        for command in line[len("RUN ") :].split("&&"):
            words = command.split()
            if words[:2] != ["pip", "install"]:
                continue
            arguments = iter(words[2:])
            for word in arguments:
                if word in ("-r", "--requirement"):
                    # Requirements files are copied next to the task root.
                    names |= _requirements_file(BACKEND / Path(next(arguments)).name)
                elif word in _PIP_VALUE_OPTIONS:
                    next(arguments)
                elif not word.startswith("-"):
                    names.add(_distribution(word))
    return names


def test_api_image_installs_no_model_runtime() -> None:
    installed = _installed_distributions("Dockerfile.api")

    assert "fastapi" in installed
    assert not installed & MODEL_RUNTIME


def test_model_runtime_rule_sees_the_analysis_image() -> None:
    """The rule above can fail: the analysis image does install both."""
    assert MODEL_RUNTIME <= _installed_distributions("Dockerfile.analysis")


def test_api_image_handlers_start_without_a_model_runtime() -> None:
    """Every handler the API image runs imports with torch and transformers missing."""
    handlers = sorted(
        module for _id, dockerfile, module in _image_handlers() if dockerfile == "Dockerfile.api"
    )
    script = "\n".join(
        [
            "import importlib, sys",
            *(f"sys.modules[{name!r}] = None" for name in sorted(MODEL_RUNTIME)),
            f"for name in {handlers!r}:",
            "    importlib.import_module(name)",
        ]
    )
    # No SSM parameter is read and no database is reached while importing.
    environment = {
        name: value for name, value in os.environ.items() if not name.endswith("_PARAMETER")
    }
    environment["DATABASE_URL"] = "postgresql://user:password@127.0.0.1:9/unreachable"

    started = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert "lambda_api" in handlers
    assert started.returncode == 0, started.stderr
