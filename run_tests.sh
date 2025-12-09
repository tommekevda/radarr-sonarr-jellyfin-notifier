#!/usr/bin/env sh
set -e

# Run all unit tests
uv run -m unittest discover -s tests
