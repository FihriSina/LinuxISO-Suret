from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import yaml

from linux_iso.assets import sha256_file
from linux_iso.builder.kiwi import UBUNTU_2604_KDE, generate_kiwi_project
from linux_iso.capture import _copy_file
from linux_iso.installer.catalog import build_catalog


def _minimal_profile(tmp_path: Path) -> Path:
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
    sddm_theme = profile / "payload/system/sddm/theme"
    sddm_theme.mkdir(parents=True)
    (sddm_theme / "Main.qml").write_text("// source theme archive\n", encoding="utf-8")
    (profile / "system-visual.json").write_text(
        '{"sddm":{"theme_captured":true,"settings":{"Current":"pardus","CursorTheme":"Breeze_Light"}}}\n',
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
            "component_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "asset_mode": "active",
            "fidelity_schema": 9,
            "visible_wallpaper": "{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg",
            "system_visual": {"sddm": {"theme_captured": True}},
            "desktop_surface": {
                "directory": "{{HOME}}/Masaüstü",
                "launchers": [],
                "launcher_count": 0,
                "applet_launchers": [],
            },
        },
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return profile


def test_v042_pardus_and_vendor_launchers_are_rewritten_to_working_target_commands(tmp_path: Path):
    home = tmp_path / "home"
    cases = {
        "pardus-mycomputer": "dolphin /",
        "/usr/bin/pardus-about --hardware": "kinfocenter",
        "pardus-update": "plasma-discover --mode update",
        "pardus-software": "plasma-discover",
        "pardus-power-manager": "systemsettings kcm_powerdevilprofilesconfig",
        "/usr/share/code/code --unity-launch %F": "flatpak run com.visualstudio.code",
        "signal-desktop %U": "flatpak run org.signal.Signal",
    }
    for index, (source_exec, expected) in enumerate(cases.items()):
        src = home / f"Masaüstü/app-{index}.desktop"
        dst = tmp_path / f"payload/app-{index}.desktop"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(f"[Desktop Entry]\nType=Application\nName=App\nExec={source_exec}\n", encoding="utf-8")
        _copy_file(src, dst, home, "desktop-surface-launcher")
        assert f"Exec={expected}" in dst.read_text(encoding="utf-8")


def test_v042_catalog_uses_portable_flatpak_fallbacks_for_vendor_apps(tmp_path: Path):
    profile = tmp_path / "profile"
    profile.mkdir()
    manifest = {
        "packages": [
            {"provider": "apt", "name": "code", "category": "development", "installer_visible": True},
            {"provider": "apt", "name": "signal-desktop", "category": "communication", "installer_visible": True},
        ]
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    catalog = build_catalog(profile)
    items = [item for group in catalog["categories"] for item in group["items"]]
    identities = {(item["provider"], item["name"]) for item in items}
    assert ("flatpak", "com.visualstudio.code") in identities
    assert ("flatpak", "org.signal.Signal") in identities
    assert ("apt", "code") not in identities
    assert ("apt", "signal-desktop") not in identities


def test_v042_target_has_runtime_compat_packages_and_safe_sddm(tmp_path: Path):
    assert "kinfocenter" in UBUNTU_2604_KDE.image_packages
    assert "plasma-discover" in UBUNTU_2604_KDE.image_packages
    assert "flatpak" in UBUNTU_2604_KDE.image_packages
    assert "plasma-discover-backend-flatpak" in UBUNTU_2604_KDE.image_packages
    assert "sddm-theme-breeze" in UBUNTU_2604_KDE.image_packages

    build = tmp_path / "build"
    generate_kiwi_project(_minimal_profile(tmp_path), build)
    target = (build / "root/usr/lib/linux-iso/apply-target-profile.py").read_text(encoding="utf-8")
    assert "Current=breeze" in target
    assert "suret-source-archive" in target
    assert "theme.conf.user" in target
    assert "suret-login-wallpaper" in target

    staged_wallpapers = list((build / "root/usr/share/wallpapers").glob("suret-login-wallpaper.*"))
    assert len(staged_wallpapers) == 1
    theme_user = build / "root/usr/share/sddm/themes/breeze/theme.conf.user"
    assert theme_user.is_file()
    assert staged_wallpapers[0].name in theme_user.read_text(encoding="utf-8")

    first_login = (build / "root/usr/lib/linux-iso/apply-first-login-fidelity.py").read_text(encoding="utf-8")
    assert "currentActivity()" in first_login
    assert "desktopsForActivity(aid)" in first_login
    subprocess.run([sys.executable, "-m", "py_compile", str(build / "root/usr/lib/linux-iso/apply-first-login-fidelity.py")], check=True)

    tree = ET.parse(build / "config.xml")
    names = {node.attrib["name"] for node in tree.findall("./packages[@type='image']/package")}
    for name in ("kinfocenter", "plasma-discover", "flatpak", "plasma-discover-backend-flatpak", "sddm-theme-breeze"):
        assert name in names


def test_v042_diagnostics_no_longer_claims_computer_protocol_support(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_minimal_profile(tmp_path), build)
    diagnose = (build / "root/usr/local/bin/suret-diagnose").read_text(encoding="utf-8")
    assert "Dolphin filesystem compatibility test" in diagnose
    assert "computer:/ KIO test" not in diagnose
    assert "currentActivity()" in diagnose


def test_v042_web_app_launchers_are_normalized_by_visible_name(tmp_path: Path):
    home = tmp_path / "home"
    cases = {
        "WhatsApp Web": "xdg-open https://web.whatsapp.com/",
        "ChatGPT": "xdg-open https://chatgpt.com/",
    }
    for index, (name, expected) in enumerate(cases.items()):
        src = home / f"Masaustu/web-{index}.desktop"
        dst = tmp_path / f"payload/web-{index}.desktop"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(
            "[Desktop Entry]\nType=Application\n"
            f"Name={name}\nExec=google-chrome --profile-directory=Default --app=https://example.invalid/%U\n",
            encoding="utf-8",
        )
        _copy_file(src, dst, home, "desktop-surface-launcher")
        assert f"Exec={expected}" in dst.read_text(encoding="utf-8")


def test_v042_flatpak_exported_favorite_launcher_is_resolved(tmp_path: Path):
    from linux_iso.desktop.kde import referenced_application_desktops

    home = tmp_path / "home"
    config = home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    config.parent.mkdir(parents=True)
    config.write_text(
        "[Containments][1][Applets][1][Configuration][General]\n"
        "launchers=applications:com.google.AndroidStudio.desktop\n",
        encoding="utf-8",
    )
    launcher = home / ".local/share/flatpak/exports/share/applications/com.google.AndroidStudio.desktop"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        "[Desktop Entry]\nType=Application\nName=Android Studio\nExec=flatpak run com.google.AndroidStudio\n",
        encoding="utf-8",
    )
    refs = referenced_application_desktops(home)
    assert launcher in refs


def test_v042_target_contains_xdg_open_for_portable_web_launchers():
    assert "xdg-utils" in UBUNTU_2604_KDE.image_packages


def test_v042_flatpak_exported_icon_is_captured_for_named_launcher(tmp_path: Path):
    from linux_iso.capture import _named_launcher_icon_files

    home = tmp_path / "home"
    icon = home / ".local/share/flatpak/exports/share/icons/hicolor/128x128/apps/com.google.AndroidStudio.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"png")
    found = _named_launcher_icon_files(home, "com.google.AndroidStudio")
    assert any(src == icon for src, _ in found)
