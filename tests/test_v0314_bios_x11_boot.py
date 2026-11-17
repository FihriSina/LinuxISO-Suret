from __future__ import annotations

import xml.etree.ElementTree as ET
from string import Template
from pathlib import Path

import yaml

from linux_iso.builder.kiwi import UBUNTU_2604_KDE, generate_kiwi_project


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    (payload / "kdeglobals").write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {
            "distro_id": "pardus",
            "distro_name": "Pardus GNU/Linux 25 (yirmibes)",
            "architecture": "x86_64",
        },
        "desktop": {
            "desktop": "kde-plasma",
            "configs": [{
                "source": "{{HOME}}/.config/kdeglobals",
                "destination": "{{HOME}}/.config/kdeglobals",
                "kind": "desktop-config",
                "sha256": None,
            }],
            "custom_assets": [],
            "widgets": [],
            "widget_details": [],
            "component_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "asset_mode": "active",
        },
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return profile


def test_v0314_recipe_includes_x11_live_session():
    for package in ("plasma-session-x11", "kwin-x11", "xorg"):
        assert package in UBUNTU_2604_KDE.image_packages


def test_v0314_generated_project_uses_bios_safe_grub_and_x11(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)

    tree = ET.parse(build / "config.xml")
    bootloader = tree.find("./preferences/type/bootloader")
    assert bootloader is not None
    assert bootloader.attrib["name"] == "grub2"
    assert bootloader.attrib["grub_template"] == "grub-live-safe.cfg.tmpl"

    grub = (build / "grub-live-safe.cfg.tmpl").read_text(encoding="utf-8")
    assert 'if [ "$${grub_platform}" = "pc" ]' in grub
    assert "linux16 ($$root)" in grub
    assert "initrd16 ($$root)" in grub
    assert "linux ($$root)" in grub
    assert "initrd ($$root)" in grub
    assert "set gfxpayload=keep" not in grub

    # Match the parameter set KIWI NG 11.1.16 passes to custom live ISO templates.
    rendered = Template(grub).substitute({
        "search_params": "--file --set=root /boot/example",
        "default_boot": "0",
        "kernel_file": "linux",
        "initrd_file": "initrd",
        "boot_options": "root=live:CDLABEL=CDROM rd.live.image",
        "failsafe_boot_options": "root=live:CDLABEL=CDROM rd.live.image nomodeset",
        "gfxmode": "auto",
        "theme": "",
        "boot_timeout": "10",
        "boot_timeout_style": "menu",
        "serial_line_setup": "",
        "title": "Linux ISO - Suret",
        "bootpath": "/boot/x86_64/loader",
        "boot_directory_name": "grub",
        "efi_image_name": "bootx64.efi",
        "terminal_input": "console",
        "terminal_output": "console",
    })
    assert "linux16 ($root)/boot/x86_64/loader/linux" in rendered
    assert "initrd16 ($root)/boot/x86_64/loader/initrd" in rendered
    assert "${grub_platform}" in rendered

    config = (build / "config.sh").read_text(encoding="utf-8")
    assert "DisplayServer=x11" in config
    assert "User=live" in config
    assert "Session=plasmax11" in config

    qemu = (build / "test-qemu.sh").read_text(encoding="utf-8")
    assert "-machine q35" in qemu
    assert "-accel tcg,thread=single -cpu max,la57=off" in qemu
    assert "-vga std" in qemu
    assert "-display gtk,gl=off" in qemu
    assert "virtio-vga" not in qemu
