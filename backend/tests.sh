#!/bin/bash

# Redirecting all terminal output from this script to go to an output file
# Creating timestamp folder
printf -v date '%(%Y-%m-%d-%H-%M-%S)T' -1
folder="_test_output/${date}"
mkdir -p "$folder"

# Save stdout to file descriptor (so it can be restored later)
exec 3>&1
exec > "$folder/_errors.txt" 2>&1

status=0

# checks for code style. Informational only for now: the codebase has
# pre-existing pylint findings this script never used to surface (it never
# checked any tool's exit code), so failing the build on every pylint
# warning today would redden CI for reasons unrelated to a given change.
# Tighten this to `|| status=1` once the existing backlog is cleared.
echo "---------- PYLINT (non-blocking) ----------"
pylint --recursive=y . > "$folder/pylint.txt"


# checks for type annotations. Also non-blocking for now — see the pylint
# note above; the same pre-existing-backlog concern applies to mypy.
echo "---------- MYPY (non-blocking) ----------"
mypy . \
    --disallow-untyped-defs \
    --disallow-incomplete-defs \
    --check-untyped-defs \
    --ignore-missing-imports \
    --no-strict-optional \
    --pretty > "$folder/mypy.txt"


# runs unit tests and reports code coverage. Blocking: a failing test means a
# real regression, not a style backlog, so this must fail the build.
echo "---------- PYTEST ----------"
coverage run -m pytest > "$folder/pytest.txt" || status=1


# searches for code security vulnerabilities. Blocking, for the same reason.
# -ll restricts this to medium+ severity: low-severity findings (e.g. bare
# except/pass) are noisy pre-existing backlog, not the kind of regression
# this gate exists to catch.
echo "---------- BANDIT (medium+ severity) ----------"
bandit -c bandit.yaml -ll -r . > "$folder/bandit.txt" || status=1


# Restore output from file descriptor 3
exec 1>&3
exec 2>&3

# Close file descriptor 3 (cleanup)
exec 3>&-

if [ "$status" -ne 0 ]; then
    echo "TEST SCRIPT FAILED (pytest and/or bandit) — see '$folder'"
else
    echo "TEST SCRIPT COMPLETE, OUTPUT CAN BE FOUND IN '$folder'"
fi

exit $status
