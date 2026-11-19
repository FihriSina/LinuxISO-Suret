from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from linux_iso.builder.kiwi import (
    UBUNTU_2604_KDE,
    UBUNTU_ARCHIVE_KEY_SHA256,
    UBUNTU_ARCHIVE_KEY_URI,
    generate_kiwi_project,
)


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


def test_v043_all_ubuntu_repositories_use_bundled_archive_signing_key():
    assert UBUNTU_2604_KDE.repositories
    assert all(repo.signing_key == UBUNTU_ARCHIVE_KEY_URI for repo in UBUNTU_2604_KDE.repositories)
    assert UBUNTU_ARCHIVE_KEY_URI.startswith("this://")


def test_v043_generated_repositories_embed_local_signing_key(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)
    root = ET.parse(build / "config.xml").getroot()
    repositories = root.findall("./repository")
    assert len(repositories) == 3
    for repository in repositories:
        source = repository.find("./source")
        assert source is not None
        signing = source.find("./signing")
        assert signing is not None
        assert signing.attrib == {"key": UBUNTU_ARCHIVE_KEY_URI}


def test_v043_bundled_key_is_staged_and_integrity_pinned(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)
    key = build / "keys/ubuntu-archive-key-2018.asc"
    assert key.is_file()
    assert hashlib.sha256(key.read_bytes()).hexdigest() == UBUNTU_ARCHIVE_KEY_SHA256
    text = key.read_text(encoding="utf-8")
    assert "Ubuntu Archive Automatic Signing Key (2018)" not in text  # binary armor has no plaintext UID
    assert text.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")
    assert text.rstrip().endswith("-----END PGP PUBLIC KEY BLOCK-----")


def test_v043_ubuntu_keyring_is_bootstrap_package():
    assert "ubuntu-keyring" in UBUNTU_2604_KDE.bootstrap_packages
