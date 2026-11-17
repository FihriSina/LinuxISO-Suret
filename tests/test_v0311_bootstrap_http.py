from __future__ import annotations

import xml.etree.ElementTree as ET
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


def test_v0311_ubuntu_bootstrap_repositories_use_http():
    assert UBUNTU_2604_KDE.repositories
    assert all(repo.url.startswith("http://") for repo in UBUNTU_2604_KDE.repositories)


def test_v0311_signing_keys_remain_https():
    assert all(
        repo.signing_key and repo.signing_key.startswith("https://")
        for repo in UBUNTU_2604_KDE.repositories
    )


def test_v0311_generated_repository_sources_use_http(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)
    root = ET.parse(build / "config.xml").getroot()
    sources = [node.find("./source") for node in root.findall("./repository")]
    assert len(sources) == 3
    assert all(source is not None for source in sources)
    assert all(source.attrib["path"].startswith("http://") for source in sources if source is not None)
