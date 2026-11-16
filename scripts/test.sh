#!/bin/sh
set -eu

# Project-local test entry point. Explicitly undo uv environment flags that can
# suppress the default development dependency group.
unset UV_NO_DEV 2>/dev/null || true
unset UV_NO_DEFAULT_GROUPS 2>/dev/null || true

uv sync --dev
exec uv run --dev pytest -q "$@"
