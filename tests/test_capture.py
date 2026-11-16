from __future__ import annotations

import os
from pathlib import Path

import yaml

from linux_iso.assets import find_referenced_assets
from linux_iso.security.sanitizer import sanitize_shell_text


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


def test_full_capture_uses_portable_destinations_and_redacts_shell_secret(tmp_path: Path, monkeypatch):
    import linux_iso.capture as capture

    home = tmp_path / "source-home"
    config = home / ".config"
    icons = home / "Pictures/icons"
    config.mkdir(parents=True)
    icons.mkdir(parents=True)

    icon = icons / "terminal-blue.svg"
    icon.write_text("<svg></svg>", encoding="utf-8")
    (config / "kdeglobals").write_text(
        f"[Icons]\nTheme=Breeze\n[Custom]\nIcon={icon}\n", encoding="utf-8"
    )
    (home / ".zshrc").write_text(
        "export GITHUB_TOKEN=super-secret\nalias ll='ls -la'\n", encoding="utf-8"
    )

    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "plasmashell 6.test"))
    monkeypatch.setattr(
        capture,
        "collect_system_info",
        lambda: {"distro_id": "ubuntu", "distro_name": "Ubuntu Test", "distro_version": "26.04"},
    )
    monkeypatch.setattr(capture, "collect_packages", lambda: [])
    monkeypatch.setattr(capture, "referenced_widgets", lambda _home: [])
    monkeypatch.setattr(capture, "user_plasmoids", lambda _home: [])
    monkeypatch.setattr(capture, "active_kde_components", lambda _home: [])

    output = tmp_path / "profile"
    manifest = capture.capture_profile(output, home)

    destinations = [x.destination for x in manifest.desktop.configs + manifest.desktop.custom_assets]
    assert "{{HOME}}/.config/kdeglobals" in destinations
    assert "{{HOME}}/Pictures/icons/terminal-blue.svg" in destinations
    assert str(tmp_path) not in "\n".join(destinations)

    zsh = (output / "payload/home/.zshrc").read_text(encoding="utf-8")
    assert "super-secret" not in zsh
    assert "alias ll" in zsh
