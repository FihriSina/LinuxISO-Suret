#!/bin/sh
set -eu

# Project-local test entry point. Explicitly undo uv environment flags that can
# suppress the default development dependency group.
unset UV_NO_DEV 2>/dev/null || true
unset UV_NO_DEFAULT_GROUPS 2>/dev/null || true
unset UV_NO_GROUP 2>/dev/null || true

uv sync --dev
# Invoke pytest as a Python module. This remains reliable even if a stale uv
# environment has lost the generated pytest console-entrypoint script.
exec uv run --dev python -m pytest -q "$@"
