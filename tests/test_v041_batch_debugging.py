from __future__ import annotations

import subprocess
from pathlib import Path
import sys

import yaml

from linux_iso.assets import sha256_file
from linux_iso.builder.kiwi import generate_kiwi_project
from linux_iso.capture import capture_profile


def _patch_capture(monkeypatch, runtime_states):
    import linux_iso.capture as capture

    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "6.test"))
    monkeypatch.setattr(
        capture,
        "collect_system_info",
        lambda: {
            "distro_id": "pardus",
            "distro_name": "Pardus GNU/Linux 25",
            "distro_name_short": "Pardus GNU/Linux",
            "distro_version": "25",
            "architecture": "x86_64",
        },
    )
    monkeypatch.setattr(capture, "collect_packages", lambda: [])
    monkeypatch.setattr(capture, "referenced_widgets", lambda _home: [])
    monkeypatch.setattr(capture, "user_plasmoids", lambda _home: [])
    monkeypatch.setattr(capture, "active_kwin_user_components", lambda _home: [])
    monkeypatch.setattr(capture, "active_kde_components", lambda _home: [])
    monkeypatch.setattr(capture, "icon_theme_inheritance_chain", lambda _home, _name: [])
    monkeypatch.setattr(capture, "_runtime_plasma_wallpaper_state", lambda _home: runtime_states)


def test_v041_runtime_primary_screen_wallpaper_beats_first_persisted_image(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    config = home / ".config"
    pictures = home / "Resimler" / "ArkaPlanlar"
    config.mkdir(parents=True)
    pictures.mkdir(parents=True)
    green = pictures / "green-mountain.jpg"
    whale = pictures / "dreamlike-whale.jpg"
    green.write_bytes(b"green")
    whale.write_bytes(b"whale")

    plasma = config / "plasma-org.kde.plasma.desktop-appletsrc"
    plasma.write_text(
        "[Containments][10]\n"
        "wallpaperplugin=org.kde.image\n"
        "[Containments][10][Wallpaper][org.kde.image][General]\n"
        f"Image=file://{green}\n"
        "[Containments][20]\n"
        "wallpaperplugin=org.kde.image\n"
        "[Containments][20][Wallpaper][org.kde.image][General]\n"
        f"Image=file://{whale}\n",
        encoding="utf-8",
    )
    _patch_capture(
        monkeypatch,
        [
            {"id": 10, "screen": 1, "plugin": "org.kde.image", "image": f"file://{green}", "slidePaths": ""},
            {"id": 20, "screen": 0, "plugin": "org.kde.image", "image": f"file://{whale}", "slidePaths": ""},
        ],
    )

    profile = tmp_path / "profile"
    manifest = capture_profile(profile, home)
    assert manifest.restore["visible_wallpaper"] == "{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg"


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home"
    wallpaper = payload / "Resimler/ArkaPlanlar/dreamlike-whale.jpg"
    wallpaper.parent.mkdir(parents=True)
    wallpaper.write_bytes(b"whale")
    config = payload / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    config.parent.mkdir(parents=True)
    config.write_text(
        "[Containments][1]\nwallpaperplugin=org.kde.image\n"
        "[Containments][1][Wallpaper][org.kde.image][General]\n"
        "Image=file://{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg\n",
        encoding="utf-8",
    )
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
            "configs": [{
                "source": "{{HOME}}/.config/plasma-org.kde.plasma.desktop-appletsrc",
                "destination": "{{HOME}}/.config/plasma-org.kde.plasma.desktop-appletsrc",
                "kind": "config",
                "sha256": sha256_file(config),
            }],
            "custom_assets": [{
                "source": "{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg",
                "destination": "{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg",
                "kind": "referenced-asset",
                "sha256": sha256_file(wallpaper),
            }],
            "widgets": [],
            "user_plasmoids": [],
            "widget_details": [],
            "component_details": [
                {"kind": "icon-theme", "name": "Tela-manjaro-dark", "source": "user-local", "bundled": False},
                {"kind": "cursor-theme", "name": "Breeze_Light", "source": "user-local", "bundled": False},
                {"kind": "color-scheme", "name": "Nordic", "source": "user-local", "bundled": False},
                {"kind": "plasma-theme", "name": "Ant-Dark", "source": "user-local", "bundled": False},
            ],
        },
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "asset_mode": "active",
            "fidelity_schema": 9,
            "visible_wallpaper": "{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg",
            "desktop_surface": {"directory": "{{HOME}}/Masaüstü", "launchers": [], "launcher_count": 0, "applet_launchers": []},
        },
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return profile


def test_v041_first_login_converges_multiple_visible_appearance_layers(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)

    state = (build / "root/usr/share/linux-iso/profile/visible-state.json").read_text(encoding="utf-8")
    script = (build / "root/usr/lib/linux-iso/apply-first-login-fidelity.py").read_text(encoding="utf-8")

    for value in ("Tela-manjaro-dark", "Breeze_Light", "Nordic", "Ant-Dark", "dreamlike-whale.jpg"):
        assert value in state
    assert "plasma-apply-cursortheme" in script
    assert "plasma-apply-colorscheme" in script
    assert "plasma-apply-desktoptheme" in script
    assert "first-login-report.json" in script
    assert "state_token = hashlib.sha256" in script
    subprocess.run([sys.executable, "-m", "py_compile", str(build / "root/usr/lib/linux-iso/apply-first-login-fidelity.py")], check=True)


def test_v041_installed_system_contains_batch_diagnostic_collector(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    script = build / "root/usr/local/bin/suret-diagnose"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    for needle in (
        "runtime-wallpaper.txt",
        "exec-health.txt",
        "desktop-installer-journal.txt",
        "computer:/ KIO test",
        "systemctl --failed",
        "first-login-report.json",
    ):
        assert needle in text
    subprocess.run(["bash", "-n", str(script)], check=True)
