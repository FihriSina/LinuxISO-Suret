from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.builder.kiwi import UBUNTU_2604_KDE, generate_kiwi_project


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    (payload / "kdeglobals").write_text("[General]\nColorScheme=BreezeDark\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "architecture": "x86_64"},
        "desktop": {"desktop": "kde-plasma", "configs": [], "custom_assets": []},
        "packages": [
            {"name": "firefox", "provider": "apt", "category": "internet", "required_for_appearance": False},
            {"name": "vlc", "provider": "apt", "category": "multimedia", "required_for_appearance": False},
        ],
        "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return profile


def test_v0316_uses_dynamic_checkbox_chooser_not_hardcoded_qml(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    fragment = yaml.safe_load((build / "root/etc/calamares/linux-iso-settings-fragment.yaml").read_text())
    instances = fragment["instances"]
    assert instances
    assert all(x["module"] == "netinstall" for x in instances)
    assert "netinstall@linuxiso_internet" in fragment["sequence_patch"]["insert_before_summary"]
    assert "packagechooserq@linuxiso_internet" not in fragment["sequence_patch"]["insert_before_summary"]
    chooser = yaml.safe_load(
        (build / "root/etc/calamares/modules/netinstall-linuxiso_internet.conf").read_text(
            encoding="utf-8"
        )
    )
    assert all(group["selected"] is True for group in chooser["groups"])
    assert all(group["subgroups"][0]["hidden"] is True for group in chooser["groups"])
    assert all(
        group["subgroups"][0]["packages"][0].startswith("linuxiso__")
        for group in chooser["groups"]
    )


def test_v0316_installer_filesystem_helpers_are_explicit():
    for package in ("dosfstools", "e2fsprogs", "parted"):
        assert package in UBUNTU_2604_KDE.image_packages


def test_v0316_qemu_creates_install_disk_and_network(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    qemu = (build / "test-qemu.sh").read_text(encoding="utf-8")
    assert "LINUX_ISO_QEMU_DISK" in qemu
    assert "LINUX_ISO_QEMU_DISK_SIZE:-40G" in qemu
    assert "qemu-img" in qemu
    assert "format=qcow2,if=virtio" in qemu
    assert "-netdev user,id=net0" in qemu
    assert "virtio-net-pci,netdev=net0" in qemu


def test_v0316_live_environment_avoids_known_shell_and_hostname_noise(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    config = (build / "config.sh").read_text(encoding="utf-8")
    assert "localhost.localdomain" in config
    assert "/home/live/.local/bin/env" in config
