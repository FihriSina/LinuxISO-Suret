from __future__ import annotations

import importlib.util
import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from linux_iso.branding import PRODUCT_NAME


def _package_version() -> str:
    try:
        return version("linux-iso")
    except PackageNotFoundError:
        return "source-tree"


def doctor_report(cwd: Path | None = None) -> str:
    cwd = (cwd or Path.cwd()).resolve()
    project_file = cwd / "pyproject.toml"
    pytest_available = importlib.util.find_spec("pytest") is not None
    suppressors = {
        name: os.environ.get(name)
        for name in ("UV_NO_DEV", "UV_NO_DEFAULT_GROUPS", "UV_PROJECT_ENVIRONMENT")
        if os.environ.get(name)
    }

    lines = [
        f"{PRODUCT_NAME} doctor",
        "=" * (len(PRODUCT_NAME) + 7),
        f"linux-iso version: {_package_version()}",
        f"Python: {platform.python_version()}",
        f"Python executable: {sys.executable}",
        f"Project directory: {cwd}",
        f"pyproject.toml: {'found' if project_file.exists() else 'not found'}",
        f"pytest available: {'yes' if pytest_available else 'no'}",
    ]

    if suppressors:
        lines.append("uv environment overrides:")
        for name, value in suppressors.items():
            lines.append(f"- {name}={value}")
    else:
        lines.append("uv environment overrides: none detected")

    if not pytest_available:
        lines.extend(
            [
                "",
                "Test dependency is missing from the active uv environment.",
                "Repair: unset UV_NO_DEV UV_NO_DEFAULT_GROUPS; uv sync --dev",
                "Then:   uv run --dev pytest -q",
            ]
        )
    return "\n".join(lines)
