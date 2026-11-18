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


def test_v0319_calamares_uses_kiwi_kernel_not_casper(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    helper = (build / "root/usr/lib/linux-iso/prepare-calamares-media").read_text()
    assert "/cdrom/boot/x86_64/loader/linux" in helper
    assert "before_bootloader_mkdirs_context.conf" in helper
    assert r"\${ROOT}/boot/vmlinuz-\$(uname -r)" in helper
    assert "/cdrom/casper/vmlinuz" not in helper


def test_v0319_ubuntu_cdrom_bootloader_context_is_neutralized(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    helper = (build / "root/usr/lib/linux-iso/prepare-calamares-media").read_text()
    assert "before_bootloader_context.conf" in helper
    assert '"*": "-/bin/true"' in helper
    assert "apt-cdrom add" not in helper


def test_v0319_bootloader_runtime_tools_are_explicit():
    assert "grub2-common" in UBUNTU_2604_KDE.image_packages
    assert "efibootmgr" in UBUNTU_2604_KDE.image_packages
