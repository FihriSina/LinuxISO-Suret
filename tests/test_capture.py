from __future__ import annotations

import os
from pathlib import Path

import yaml

from mydistro.assets import find_referenced_assets
from mydistro.security.sanitizer import sanitize_shell_text


def test_shell_secret_redaction():
    source = "export GITHUB_TOKEN=abc123\nalias ll='ls -la'\n"
    result = sanitize_shell_text(source)
    assert "abc123" not in result.text
    assert "alias ll" in result.text
    assert result.redacted_lines == 1


def test_referenced_asset_detection(tmp_path: Path):
    home = tmp_path / "home"
    cfg = home / ".config"
    icons = home / "Pictures/icons"
    cfg.mkdir(parents=True)
    icons.mkdir(parents=True)
    icon = icons / "custom.svg"
    icon.write_text("<svg></svg>", encoding="utf-8")
    config = cfg / "launcher.conf"
    config.write_text(f"Icon={icon}\n", encoding="utf-8")

    found = find_referenced_assets([config], home)
    assert icon.resolve() in found
