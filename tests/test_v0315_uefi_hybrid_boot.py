from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from linux_iso.builder.kiwi import generate_kiwi_project


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    (payload / "kdeglobals").write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "distro_name": "Pardus", "architecture": "x86_64"},
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
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return profile


def test_v0315_iso_recipe_is_explicit_efi_hybrid(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)

    tree = ET.parse(build / "config.xml")
    image_type = tree.find("./preferences/type[@image='iso']")
    assert image_type is not None
    assert image_type.attrib["firmware"] == "efi"
    assert image_type.attrib["gpt_hybrid_mbr"] == "true"


def test_v0315_qemu_defaults_to_ovmf_uefi_and_keeps_bios_override(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)

    qemu = (build / "test-qemu.sh").read_text(encoding="utf-8")
    assert "FIRMWARE=${LINUX_ISO_QEMU_FIRMWARE:-uefi}" in qemu
    assert "/usr/share/OVMF/OVMF_CODE_4M.fd" in qemu
    assert "/usr/share/OVMF/OVMF_VARS_4M.fd" in qemu
    assert "if=pflash,format=raw,readonly=on" in qemu
    assert "LINUX_ISO_QEMU_FIRMWARE=bios" in qemu
