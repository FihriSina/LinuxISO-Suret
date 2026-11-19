from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

from linux_iso.builder.kiwi import generate_kiwi_project
from linux_iso.capture import _copy_file


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    (profile / "payload/home").mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "source": {
            "distro_id": "pardus",
            "distro_name": "Pardus GNU/Linux 25",
            "distro_name_short": "Pardus GNU/Linux",
            "distro_version": "25",
            "architecture": "x86_64",
        },
        "desktop": {
            "desktop": "kde-plasma",
            "configs": [],
            "custom_assets": [],
            "widgets": [],
            "user_plasmoids": [],
            "widget_details": [],
            "component_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "asset_mode": "active",
            "fidelity_schema": 7,
        },
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return profile


def test_v0330_pardus_live_identity_masks_kubuntu_installers(tmp_path: Path):
    profile = _profile(tmp_path)
    build = tmp_path / "build"
    generate_kiwi_project(profile, build)

    tree = ET.parse(build / "config.xml")
    live = tree.find("./users/user[@name='live']")
    assert live is not None
    assert live.attrib["realname"] == "Pardus Live"

    masker = (build / "root/usr/lib/linux-iso/hide-foreign-installers").read_text(
        encoding="utf-8"
    )
    assert "install kubuntu" in masker
    assert "kubuntu-installer-prompt" in masker
    assert "Hidden=true" in masker
    assert "/usr/local/share/applications" in masker

    config = (build / "config.sh").read_text(encoding="utf-8")
    assert "python3 /usr/lib/linux-iso/hide-foreign-installers" in config
    assert "/usr/local/share/applications/linux-iso-installer.desktop" in config
    assert "Name=Install Pardus" in config
    assert "Name[tr]=Pardus'u Kur" in config

    qemu = (build / "test-qemu.sh").read_text(encoding="utf-8")
    assert "Suret - LIVE ISO" in qemu
    assert "Suret - INSTALLED SYSTEM" in qemu


def test_v0330_pardus_mycomputer_launcher_gets_portable_kde_exec(tmp_path: Path):
    home = tmp_path / "home"
    src = home / "Masaüstü/Bilgisayar.desktop"
    dst = tmp_path / "profile/payload/home/Masaüstü/Bilgisayar.desktop"
    src.parent.mkdir(parents=True)
    src.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Bilgisayar\n"
        "Exec=pardus-mycomputer\n"
        "Icon=computer\n",
        encoding="utf-8",
    )

    captured = _copy_file(src, dst, home, "desktop-surface-launcher")
    text = dst.read_text(encoding="utf-8")
    assert "Exec=dolphin computer:/" in text
    assert "pardus-mycomputer" not in text
    assert captured.sha256


def test_v0331_installer_launcher_uses_active_xdg_desktop_directory(tmp_path: Path):
    profile = _profile(tmp_path)
    build = tmp_path / "build"
    generate_kiwi_project(profile, build)

    config = (build / "config.sh").read_text(encoding="utf-8")
    assert "/home/live/.config/user-dirs.dirs" in config
    assert "XDG_DESKTOP_DIR" in config
    assert "desktop_dir=/home/live/Desktop" in config
    assert 'desktop_dir=$XDG_DESKTOP_DIR' in config
    assert "Pardus'u Kur.desktop" in config
