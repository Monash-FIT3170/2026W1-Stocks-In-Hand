#!/bin/bash

# put any properly formed bash commands below to run unit tests
mypy . \
    --disallow-untyped-defs \
    --disallow-incomplete-defs \
    --check-untyped-defs \
    --ignore-missing-imports \
    --no-strict-optional \
    --pretty