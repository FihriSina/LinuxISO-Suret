from __future__ import annotations

from pathlib import Path
import yaml

from linux_iso.assets import sha256_file
from linux_iso.builder.kiwi import generate_kiwi_project
from linux_iso.capture import capture_profile
from linux_iso.verification import verify_profile


def _patch_capture(monkeypatch):
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
    monkeypatch.setattr(capture, "_runtime_plasma_wallpaper_state", lambda _home: [])


def test_v040_capture_records_portable_visible_wallpaper(tmp_path: Path, monkeypatch):
    _patch_capture(monkeypatch)
    home = tmp_path / "home"
    config = home / ".config"
    pictures = home / "Resimler" / "ArkaPlanlar"
    config.mkdir(parents=True)
    pictures.mkdir(parents=True)
    whale = pictures / "dreamlike-whale.jpg"
    whale.write_bytes(b"whale")
    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1]\n"
        "wallpaperplugin=org.kde.image\n"
        "[Containments][1][Wallpaper][org.kde.image][General]\n"
        f"Image=file://{whale}\n",
        encoding="utf-8",
    )

    profile = tmp_path / "profile"
    manifest = capture_profile(profile, home)

    assert manifest.restore["fidelity_schema"] == 9
    assert manifest.restore["visible_wallpaper"] == "{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg"
    assert verify_profile(profile).ok


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
            "configs": [
                {
                    "source": "{{HOME}}/.config/plasma-org.kde.plasma.desktop-appletsrc",
                    "destination": "{{HOME}}/.config/plasma-org.kde.plasma.desktop-appletsrc",
                    "kind": "config",
                    "sha256": sha256_file(config),
                }
            ],
            "custom_assets": [
                {
                    "source": "{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg",
                    "destination": "{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg",
                    "kind": "referenced-asset",
                    "sha256": sha256_file(wallpaper),
                }
            ],
            "widgets": [],
            "user_plasmoids": [],
            "widget_details": [],
            "component_details": [
                {"kind": "icon-theme", "name": "Tela-manjaro-dark", "source": "user-local", "bundled": False}
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


def test_v040_staging_has_first_login_convergence_and_one_window_install_flow(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)

    state = (build / "root/usr/share/linux-iso/profile/visible-state.json").read_text(encoding="utf-8")
    first_login = (build / "root/usr/lib/linux-iso/apply-first-login-fidelity.py").read_text(encoding="utf-8")
    autostart = (build / "root/etc/xdg/autostart/linux-iso-first-login-fidelity.desktop").read_text(encoding="utf-8")
    qemu = (build / "test-qemu.sh").read_text(encoding="utf-8")

    assert "dreamlike-whale.jpg" in state
    assert "Tela-manjaro-dark" in state
    assert "org.kde.PlasmaShell.evaluateScript" in first_login
    assert "kbuildsycoca6" in first_login
    assert "apply-first-login-fidelity.py" in autostart

    assert 'MODE=${2:-${LINUX_ISO_QEMU_MODE:-install}}' in qemu
    assert "-boot once=d,menu=on" in qemu
    assert "-no-reboot" not in qemu
    assert "linux-iso-suret-test-OVMF_VARS.fd" in qemu
    assert 'rm -f "$DISK" "$VARS_STORE"' in qemu
    assert "it will reboot directly into the installed disk" in qemu


def test_v040_optional_apt_installs_are_isolated_per_package(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    job = (build / "root/usr/share/linux-iso/calamares/modules/linuxiso-install/main.py").read_text(encoding="utf-8")
    firstboot = (build / "root/usr/lib/linux-iso/firstboot.py").read_text(encoding="utf-8")

    assert 'for item in items:' in job
    assert '["apt-get", "install", "-y", item["name"]]' in job
    assert 'for item in items:' in firstboot
    assert '["apt-get", "install", "-y", item["name"]]' in firstboot
