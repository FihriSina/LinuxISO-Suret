from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.builder.kiwi import UBUNTU_2604_KDE, generate_kiwi_project


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    (profile / "payload/home/.config").mkdir(parents=True)
    (profile / "payload/home/.config/kdeglobals").write_text("[General]\nColorScheme=BreezeDark\n")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "architecture": "x86_64"},
        "desktop": {"desktop": "kde-plasma", "configs": [], "custom_assets": []},
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    return profile


def test_v0317_calamares_uses_kiwi_liveos_source(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    helper = (build / "root/usr/lib/linux-iso/prepare-calamares-media").read_text()
    assert "/cdrom/LiveOS/squashfs.img" in helper
    assert "/etc/calamares/modules/unpackfs.conf" in helper
    assert "sourcefs: \"squashfs\"" in helper
    launcher = (build / "root/usr/bin/linux-iso-installer").read_text()
    assert "prepare-calamares-media" in launcher


def test_v0317_live_screen_lock_is_disabled(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    config = (build / "config.sh").read_text()
    assert "kscreenlockerrc" in config
    assert "Autolock=false" in config
    assert "LockOnResume=false" in config


def test_v0317_konsole_is_explicit_in_image():
    assert "konsole" in UBUNTU_2604_KDE.image_packages
