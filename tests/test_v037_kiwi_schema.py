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


def test_v037_kiwi_11116_bootloader_is_child_element(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)
    tree = ET.parse(build / "config.xml")
    image_type = tree.find("./preferences/type[@image='iso']")
    assert image_type is not None
    assert "bootloader" not in image_type.attrib
    bootloader = image_type.find("./bootloader")
    assert bootloader is not None
    assert bootloader.attrib["name"] == "grub2"
    assert bootloader.attrib.get("grub_template") == "grub-live-safe.cfg.tmpl"


def test_v037_generated_xml_matches_documented_iso_shape(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)
    tree = ET.parse(build / "config.xml")
    image_type = tree.find("./preferences/type")
    assert image_type is not None
    assert image_type.attrib["image"] == "iso"
    assert image_type.attrib["primary"] == "true"
    assert image_type.attrib["flags"] == "overlay"
    assert image_type.attrib["filesystem"] == "squashfs"
    assert image_type.attrib["firmware"] == "efi"
    assert image_type.attrib["gpt_hybrid_mbr"] == "true"
