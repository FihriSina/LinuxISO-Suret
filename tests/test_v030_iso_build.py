from __future__ import annotations

import os
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from linux_iso.buildenv import build_host_report
from linux_iso.builder.kiwi import generate_kiwi_project
from linux_iso.portability import portability_report


def _profile(tmp_path: Path, widget_min: str = "6.0") -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    cfg = payload / "kdeglobals"
    cfg.write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "ubuntu", "distro_name": "Ubuntu", "architecture": "x86_64"},
        "desktop": {
            "desktop": "kde-plasma",
            "configs": [
                {
                    "source": "{{HOME}}/.config/kdeglobals",
                    "destination": "{{HOME}}/.config/kdeglobals",
                    "kind": "desktop-config",
                    "sha256": None,
                }
            ],
            "custom_assets": [],
            "widgets": ["com.example.widget"],
            "widget_details": [
                {
                    "id": "com.example.widget",
                    "source": "user-local",
                    "bundled": True,
                    "plasma_api_minimum_version": widget_min,
                }
            ],
            "component_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return profile


def test_v030_staging_creates_live_session_and_build_helpers(tmp_path: Path):
    profile = _profile(tmp_path)
    destination = tmp_path / "build"
    generate_kiwi_project(profile, destination)

    tree = ET.parse(destination / "config.xml")
    live = tree.find("./users/user[@name='live']")
    assert live is not None
    assert live.attrib["home"] == "/home/live"

    patcher = destination / "root/usr/lib/linux-iso/patch-calamares.py"
    assert "from linux_iso" not in patcher.read_text(encoding="utf-8")

    live_apply = destination / "root/usr/lib/linux-iso/apply-live-profile.py"
    compile(live_apply.read_text(encoding="utf-8"), str(live_apply), "exec")

    config = (destination / "config.sh").read_text(encoding="utf-8")
    assert "User=live" in config
    assert "Session=plasma" in config
    assert "linux-iso-installer.desktop" in config

    build = (destination / "build.sh").read_text(encoding="utf-8")
    assert "direct KIWI container backend" in build
    assert "--entrypoint /usr/bin/kiwi-ng" in build
    assert "system build --description /description --target-dir /result" in build
    assert "systemd-inhibit --what=sleep --mode=block" in build
    assert "sleep:idle" not in build
    assert "build-session.log" in build
    assert "resource-monitor.log" in build
    assert "nice -n" in build
    assert "ionice -c 2" in build
    assert "kiwi-ng image info" in build
    assert "--resolve-package-list" in build

    qemu = (destination / "test-qemu.sh").read_text(encoding="utf-8")
    assert "qemu-system-x86_64" in qemu
    assert "-cdrom" in qemu
    assert "LINUX_ISO_QEMU_MEMORY:-4096" in qemu
    assert "LINUX_ISO_QEMU_CPUS:-2" in qemu


def test_portability_blocks_widget_newer_than_target_plasma(tmp_path: Path):
    profile = _profile(tmp_path, widget_min="7.0")
    result = portability_report(profile, recipe_id="ubuntu-26.04-kde")
    assert result.ready is False
    assert any("requires Plasma 7.0+" in item for item in result.blockers)


def test_build_host_report_prefers_boxbuild(monkeypatch, tmp_path: Path):
    import linux_iso.buildenv as env

    monkeypatch.setattr(env, "parse_os_release", lambda: {"ID": "pardus", "PRETTY_NAME": "Pardus"})
    monkeypatch.setattr(env.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(env, "_tool", lambda name: f"/usr/bin/{name}" if name in {"uv", "podman", "kiwi-boxbuild", "qemu-system-x86_64"} else None)
    monkeypatch.setattr(env, "_kvm_accessible", lambda: (True, "/dev/kvm is readable and writable"))
    monkeypatch.setattr(env.shutil, "disk_usage", lambda _: types.SimpleNamespace(total=40 * 1024**3, used=10 * 1024**3, free=30 * 1024**3))

    report = build_host_report()
    assert report.recommended_backend == "container"
    assert report.ready is True
    assert any("isolated container backend is preferred" in item for item in report.warnings)
