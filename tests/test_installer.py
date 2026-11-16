from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from linux_iso.builder.kiwi import generate_kiwi_project
from linux_iso.installer.catalog import build_catalog


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    (payload / "kdeglobals").write_text("[General]\nColorScheme=BreezeDark\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "ubuntu", "distro_version": "26.04"},
        "desktop": {"desktop": "kde-plasma", "configs": [], "custom_assets": []},
        "packages": [
            {
                "name": "kvantum",
                "provider": "apt",
                "category": "system",
                "required_for_appearance": True,
                "reason": "appearance",
                "source": None,
            },
            {
                "name": "firefox",
                "provider": "apt",
                "category": "internet",
                "required_for_appearance": False,
                "reason": None,
                "source": None,
            },
            {
                "name": "lib-internal-example",
                "provider": "apt",
                "category": "other",
                "required_for_appearance": False,
                "reason": None,
                "source": None,
                "installer_visible": False,
                "visibility_reason": "hidden system package",
            },
            {
                "name": "org.videolan.VLC",
                "provider": "flatpak",
                "category": "multimedia",
                "required_for_appearance": False,
                "reason": None,
                "source": "flathub",
                "source_url": "https://dl.flathub.org/repo/flathub.flatpakrepo",
            },
        ],
        "security": {},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home"},
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return profile


def test_catalog_separates_appearance_requirements(tmp_path: Path):
    catalog = build_catalog(_profile(tmp_path))
    assert [x["name"] for x in catalog["required_for_appearance"]] == ["kvantum"]
    categories = {x["id"]: x for x in catalog["categories"]}
    assert categories["internet"]["items"][0]["name"] == "firefox"
    assert categories["multimedia"]["items"][0]["source"] == "flathub"
    assert categories["multimedia"]["items"][0]["source_url"].startswith("https://")
    assert catalog["hidden_native_packages"] == 1
    assert all(
        item["name"] != "lib-internal-example"
        for category in catalog["categories"]
        for item in category["items"]
    )


def test_stage_iso_project_contains_profile_installer_and_required_packages(tmp_path: Path):
    profile = _profile(tmp_path)
    destination = tmp_path / "build"
    generate_kiwi_project(profile, destination)

    ET.parse(destination / "config.xml")
    xml = (destination / "config.xml").read_text(encoding="utf-8")
    assert 'name="kvantum"' in xml
    assert 'name="flatpak"' in xml
    assert (destination / "root/usr/share/linux-iso/profile/payload/home/.config/kdeglobals").is_file()
    assert (destination / "root/usr/share/linux-iso/profile/catalog.json").is_file()
    assert (destination / "root/usr/share/linux-iso/calamares/modules/linuxiso-install/main.py").is_file()
    assert (destination / "root/etc/calamares/modules/packagechooser-linuxiso_internet.conf").is_file()
    fragment = yaml.safe_load(
        (destination / "root/etc/calamares/linux-iso-settings-fragment.yaml").read_text(encoding="utf-8")
    )
    assert "packagechooserq@linuxiso_internet" in fragment["sequence_patch"]["insert_before_summary"]

    catalog = json.loads(
        (destination / "root/usr/share/linux-iso/profile/catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["required_for_appearance"][0]["name"] == "kvantum"

    # Generated Python is deployment code, so syntax-check it as part of staging tests.
    compile(
        (destination / "root/usr/share/linux-iso/calamares/modules/linuxiso-install/main.py").read_text(encoding="utf-8"),
        "linuxiso-install/main.py",
        "exec",
    )
    compile(
        (destination / "root/usr/lib/linux-iso/firstboot.py").read_text(encoding="utf-8"),
        "firstboot.py",
        "exec",
    )
    compile(
        (destination / "root/usr/lib/linux-iso/patch-calamares.py").read_text(encoding="utf-8"),
        "patch-calamares.py",
        "exec",
    )
