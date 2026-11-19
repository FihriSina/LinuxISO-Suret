from __future__ import annotations

from pathlib import Path

from linux_iso.builder.kiwi import generate_kiwi_project
from linux_iso.capture import capture_profile
from linux_iso.verification import verify_profile


def _patch_capture(monkeypatch):
    import linux_iso.capture as capture

    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "6.test"))
    monkeypatch.setattr(
        capture,
        "collect_system_info",
        lambda: {"distro_id": "pardus", "distro_name": "Pardus Test", "architecture": "x86_64"},
    )
    monkeypatch.setattr(capture, "collect_packages", lambda: [])
    monkeypatch.setattr(capture, "referenced_widgets", lambda _home: [])
    monkeypatch.setattr(capture, "user_plasmoids", lambda _home: [])
    monkeypatch.setattr(capture, "active_kwin_user_components", lambda _home: [])
    monkeypatch.setattr(capture, "active_kde_components", lambda _home: [])
    monkeypatch.setattr(capture, "icon_theme_inheritance_chain", lambda _home, _name: [])


def test_v0325_capture_bundles_panel_launcher_and_wallpaper_directory(tmp_path: Path, monkeypatch):
    import linux_iso.capture as capture

    _patch_capture(monkeypatch)
    home = tmp_path / "home"
    config = home / ".config"
    config.mkdir(parents=True)

    wallpaper_dir = tmp_path / "whale-wallpaper"
    wallpaper_dir.mkdir()
    (wallpaper_dir / "whale.png").write_bytes(b"whale")

    launcher = tmp_path / "code.desktop"
    launcher.write_text(
        "[Desktop Entry]\nType=Application\nName=Code\nExec=code\nIcon=visual-studio-code\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(capture, "referenced_application_desktops", lambda _home: [launcher])
    launcher_icon = tmp_path / "visual-studio-code.svg"
    launcher_icon.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(
        capture,
        "_named_launcher_icon_files",
        lambda _home, _name: [
            (launcher_icon, Path(".local/share/icons/hicolor/scalable/apps/visual-studio-code.svg"))
        ],
    )

    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1][Wallpaper][org.kde.image][General]\n"
        f"Image=file://{wallpaper_dir}\n"
        "[Containments][2][Applets][3][Configuration][General]\n"
        "launchers=applications:code.desktop\n",
        encoding="utf-8",
    )

    profile = tmp_path / "profile"
    manifest = capture_profile(profile, home)

    assert manifest.restore["fidelity_schema"] == 6
    assert (profile / "payload/home/.local/share/applications/code.desktop").is_file()
    assert (
        profile / "payload/home/.local/share/icons/hicolor/scalable/apps/visual-studio-code.svg"
    ).is_file()
    copied_wallpapers = list(
        (profile / "payload/home/.local/share/linux-iso/captured-wallpapers").glob("*/whale.png")
    )
    assert len(copied_wallpapers) == 1
    restored_config = (
        profile / "payload/home/.config/plasma-org.kde.plasma.desktop-appletsrc"
    ).read_text(encoding="utf-8")
    assert str(wallpaper_dir) not in restored_config
    assert "{{HOME}}/.local/share/linux-iso/captured-wallpapers/" in restored_config
    assert verify_profile(profile).ok


def _minimal_profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    (payload / "kdeglobals").write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")
    (profile / "manifest.yaml").write_text(
        "schema_version: 1\n"
        "source:\n  distro_id: pardus\n  architecture: x86_64\n"
        "desktop:\n  desktop: kde-plasma\n  configs: []\n  custom_assets: []\n"
        "packages: []\nsecurity:\n  safe_mode: true\n"
        "restore:\n  home_placeholder: '{{HOME}}'\n  payload_root: payload/home\n"
        "  asset_mode: active\n  fidelity_schema: 2\n",
        encoding="utf-8",
    )
    return profile


def test_v0325_target_profile_job_is_mandatory_and_qemu_can_boot_installed_disk(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_minimal_profile(tmp_path), build)

    patcher = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text(
        encoding="utf-8"
    )
    target = (build / "root/usr/lib/linux-iso/apply-target-profile.py").read_text(
        encoding="utf-8"
    )
    qemu = (build / "test-qemu.sh").read_text(encoding="utf-8")

    assert 'profile_job = "shellprocess@linuxiso_apply_target_profile"' in patcher
    assert 'item == "users" or item.startswith("users@")' in patcher
    assert "target-profile job is missing" in patcher
    assert "restored wallpaper asset is missing" in target
    assert 'MODE=${2:-${LINUX_ISO_QEMU_MODE:-live}}' in qemu
    assert 'MODE" = installed' in qemu or '"$MODE" = installed' in qemu
    assert "-boot c" in qemu
