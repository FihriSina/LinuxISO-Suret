from __future__ import annotations

import importlib.util
import os
import platform
import shutil
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
    pytest_module_available = importlib.util.find_spec("pytest") is not None
    pytest_executable = shutil.which("pytest")
    project_pytest = cwd / ".venv" / "bin" / "pytest"
    project_python = cwd / ".venv" / "bin" / "python"
    suppressors = {
        name: os.environ.get(name)
        for name in (
            "UV_NO_DEV",
            "UV_NO_DEFAULT_GROUPS",
            "UV_NO_GROUP",
            "UV_PROJECT_ENVIRONMENT",
        )
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
        f"project .venv python: {'yes' if project_python.exists() else 'no'}",
        f"pytest module importable: {'yes' if pytest_module_available else 'no'}",
        f"pytest executable on PATH: {pytest_executable or 'no'}",
        f"project .venv pytest script: {'yes' if project_pytest.exists() else 'no'}",
    ]

    if suppressors:
        lines.append("uv environment overrides:")
        for name, value in suppressors.items():
            lines.append(f"- {name}={value}")
    else:
        lines.append("uv environment overrides: none detected")

    if pytest_module_available and not pytest_executable:
        lines.extend(
            [
                "",
                "pytest is importable but its console entry point is missing.",
                "This usually means the project .venv is stale or partially damaged.",
                "Repair: rm -rf .venv && uv sync --dev",
                "Test:   uv run --dev python -m pytest -q",
            ]
        )
    elif not pytest_module_available:
        lines.extend(
            [
                "",
                "The pytest development dependency is missing from the project environment.",
                "Repair: rm -rf .venv && uv sync --dev",
                "Test:   uv run --dev python -m pytest -q",
            ]
        )

    return "\n".join(lines)
