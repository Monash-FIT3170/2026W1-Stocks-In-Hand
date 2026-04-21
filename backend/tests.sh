#!/bin/bash

# checks for code style
echo "---------- PYLINT ----------"
pylint --recursive=y .

# checks for type annotations
echo "---------- MYPY ----------"
mypy . \
    --disallow-untyped-defs \
    --disallow-incomplete-defs \
    --check-untyped-defs \
    --ignore-missing-imports \
    --no-strict-optional \
    --pretty

# runs unit tests and reports code coverage
echo "---------- PYTEST ----------"
coverage run -m pytest

# searches for code security vulnerabilities
echo "---------- BANDIT ----------"
bandit -c bandit.yaml -r .