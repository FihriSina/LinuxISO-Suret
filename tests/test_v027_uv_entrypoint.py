from __future__ import annotations

from pathlib import Path

import linux_iso.diagnostics as diagnostics


def test_test_script_uses_python_module_invocation():
    text = Path("scripts/test.sh").read_text(encoding="utf-8")
    assert "uv run --dev python -m pytest -q" in text
    assert "uv run --dev pytest -q" not in text


def test_repair_script_recreates_project_environment():
    text = Path("scripts/repair-env.sh").read_text(encoding="utf-8")
    assert "rm -rf .venv" in text
    assert "uv sync --dev" in text
    assert "import pytest" in text


def test_doctor_detects_missing_console_entrypoint(monkeypatch, tmp_path: Path):
    class Spec:
        pass

    monkeypatch.setattr(diagnostics.importlib.util, "find_spec", lambda name: Spec() if name == "pytest" else None)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: None)
    report = diagnostics.doctor_report(tmp_path)
    assert "pytest module importable: yes" in report
    assert "pytest executable on PATH: no" in report
    assert "console entry point is missing" in report
    assert "python -m pytest -q" in report
