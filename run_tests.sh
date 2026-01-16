#!/usr/bin/env sh
set -e

# Run all unit tests
PYTHONPATH=src uv run -m unittest discover -s tests
