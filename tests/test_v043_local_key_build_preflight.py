from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.builder.kiwi import UBUNTU_ARCHIVE_KEY_SHA256, generate_kiwi_project


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    (payload / "kdeglobals").write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "distro_name": "Pardus GNU/Linux 25", "architecture": "x86_64"},
        "desktop": {"desktop": "kde-plasma", "configs": [{"source": "{{HOME}}/.config/kdeglobals", "destination": "{{HOME}}/.config/kdeglobals", "kind": "desktop-config", "sha256": None}], "custom_assets": [], "widgets": [], "widget_details": [], "component_details": []},
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return profile


def test_v043_generated_build_preflights_local_key(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    script = (build / "build.sh").read_text(encoding="utf-8")
    assert "KEY_FILE=$HERE/keys/ubuntu-archive-key-2018.asc" in script
    assert UBUNTU_ARCHIVE_KEY_SHA256 in script
    assert "archive.ubuntu.com/ubuntu/project/ubuntu-archive-keyring.gpg" not in (build / "config.xml").read_text(encoding="utf-8")
