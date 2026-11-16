from __future__ import annotations

from pathlib import Path

from linux_iso.diagnostics import doctor_report


def test_doctor_reports_uv_suppressor(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("UV_NO_DEV", "1")
    report = doctor_report(tmp_path)
    assert "UV_NO_DEV=1" in report


def test_doctor_is_ascii_branded(tmp_path: Path):
    report = doctor_report(tmp_path)
    assert report.startswith("Linux ISO - Suret doctor")
    assert report.isascii()


def test_pyproject_explicitly_enables_dev_group():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'default-groups = ["dev"]' in text
    assert '"pytest>=8.3,<10"' in text
