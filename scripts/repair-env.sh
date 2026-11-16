#!/bin/sh
set -eu

unset UV_NO_DEV 2>/dev/null || true
unset UV_NO_DEFAULT_GROUPS 2>/dev/null || true
unset UV_NO_GROUP 2>/dev/null || true

rm -rf .venv
uv sync --dev
uv run --dev python -c 'import pytest, sys; print("pytest", pytest.__version__); print("python", sys.executable)'
