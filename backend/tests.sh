#!/bin/bash

# Redirecting all terminal output from this script to go to an output file
# Creating timestamp folder 
printf -v date '%(%Y-%m-%d-%H-%M-%S)T' -1
folder="/test_output/${date}"
mkdir $folder

# Save stdout to file descriptor (so it can be restored later)
exec 3>&1
exec > "$folder/_errors.txt" 2>&1


# checks for code style
echo "---------- PYLINT ----------"
pylint --recursive=y . > $folder/pylint.txt


# checks for type annotations
echo "---------- MYPY ----------"
mypy . \
    --disallow-untyped-defs \
    --disallow-incomplete-defs \
    --check-untyped-defs \
    --ignore-missing-imports \
    --no-strict-optional \
    --pretty > $folder/mypy.txt


# runs unit tests and reports code coverage
echo "---------- PYTEST ----------"
coverage run -m pytest > $folder/pytest.txt


# searches for code security vulnerabilities
echo "---------- BANDIT ----------"
bandit -c bandit.yaml -r . > $folder/bandit.txt


# Restore output from file descriptor 3
exec 1>&3
exec 2>&3

# Close file descriptor 3 (cleanup)
exec 3>&-

echo "TEST SCRIPT COMPLETE, OUTPUT CAN BE FOUND IN '$folder'"