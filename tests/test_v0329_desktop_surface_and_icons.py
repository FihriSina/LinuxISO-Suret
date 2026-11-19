from __future__ import annotations

from pathlib import Path

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


def _fake_png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


def test_v0329_captures_localized_visible_desktop_launcher(tmp_path: Path, monkeypatch):
    _patch_capture(monkeypatch)
    home = tmp_path / "home"
    config = home / ".config"
    desktop = home / "Masaüstü"
    config.mkdir(parents=True)
    desktop.mkdir(parents=True)

    (config / "user-dirs.dirs").write_text(
        'XDG_DESKTOP_DIR="$HOME/Masaüstü"\n', encoding="utf-8"
    )
    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1]\nplugin=org.kde.plasma.folder\n",
        encoding="utf-8",
    )
    computer = desktop / "Bilgisayar.desktop"
    computer.write_text(
        "[Desktop Entry]\nType=Application\nName=Bilgisayar\nExec=xdg-open computer:///\nIcon=computer\n",
        encoding="utf-8",
    )
    computer.chmod(0o755)
    # A personal document on the desktop must not be silently embedded.
    (desktop / "private-notes.txt").write_text("do not capture", encoding="utf-8")

    profile = tmp_path / "profile"
    manifest = capture_profile(profile, home)

    assert manifest.restore["fidelity_schema"] == 9
    surface = manifest.restore["desktop_surface"]
    assert surface["directory"] == "{{HOME}}/Masaüstü"
    assert surface["launchers"] == ["{{HOME}}/Masaüstü/Bilgisayar.desktop"]
    assert (profile / "payload/home/Masaüstü/Bilgisayar.desktop").is_file()
    assert not (profile / "payload/home/Masaüstü/private-notes.txt").exists()
    assert (profile / "payload/home/.config/user-dirs.dirs").is_file()
    assert verify_profile(profile).ok


def test_v0329_prefers_scalable_or_high_resolution_installer_icon(tmp_path: Path):
    from linux_iso.builder.calamares import _captured_app_icon

    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    icons32 = profile / "payload/home/.local/share/icons/hicolor/32x32/apps"
    icons256 = profile / "payload/home/.local/share/icons/hicolor/256x256/apps"
    scalable = profile / "payload/home/.local/share/icons/hicolor/scalable/apps"
    apps.mkdir(parents=True)
    icons32.mkdir(parents=True)
    icons256.mkdir(parents=True)
    scalable.mkdir(parents=True)

    (apps / "firefox.desktop").write_text(
        "[Desktop Entry]\nName=Firefox\nExec=firefox\nIcon=firefox\n", encoding="utf-8"
    )
    (icons32 / "firefox.png").write_bytes(_fake_png(32, 32))
    (icons256 / "firefox.png").write_bytes(_fake_png(256, 256))
    vector = scalable / "firefox.svg"
    vector.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")

    chosen = _captured_app_icon(
        profile,
        {"id": "apt-firefox", "name": "firefox", "display_name": "Firefox"},
    )
    assert chosen == vector


def test_v0329_card_qml_does_not_upscale_tiny_icon_to_full_cover(tmp_path: Path):
    from linux_iso.builder.calamares import _category_qml

    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    icons = profile / "payload/home/.local/share/icons/hicolor/scalable/apps"
    apps.mkdir(parents=True)
    icons.mkdir(parents=True)
    (apps / "firefox.desktop").write_text(
        "[Desktop Entry]\nName=Firefox\nExec=firefox\nIcon=firefox\n", encoding="utf-8"
    )
    (icons / "firefox.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    cards = tmp_path / "cards"
    cards.mkdir()
    qml = _category_qml(
        profile,
        {
            "id": "internet",
            "label": "Internet",
            "items": [
                {
                    "id": "apt-firefox",
                    "name": "firefox",
                    "display_name": "Firefox",
                    "description": "Web browser",
                    "provider": "apt",
                }
            ],
        },
        {"accent": "#123456"},
        cards,
    )
    assert 'width: modelData.imageKind === "icon" ? 104 : parent.width' in qml
    assert 'sourceSize.width: modelData.imageKind === "icon" ? 256 : 720' in qml
    assert "mipmap: true" in qml


def test_v0329_captures_plasma_icon_applet_launcher_and_rewrites_source_path(tmp_path: Path, monkeypatch):
    _patch_capture(monkeypatch)
    home = tmp_path / "home"
    config = home / ".config"
    config.mkdir(parents=True)
    system_apps = tmp_path / "source-system-apps"
    system_apps.mkdir()
    launcher = system_apps / "pardus-mycomputer.desktop"
    launcher.write_text(
        "[Desktop Entry]\nType=Application\nName=Bilgisayar\nExec=pardus-mycomputer\nIcon=computer\n",
        encoding="utf-8",
    )
    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1][Applets][9]\n"
        "plugin=org.kde.plasma.icon\n"
        "[Containments][1][Applets][9][Configuration][General]\n"
        f"url=file://{launcher}\n",
        encoding="utf-8",
    )

    profile = tmp_path / "profile"
    manifest = capture_profile(profile, home)
    copied = profile / "payload/home/.local/share/applications/pardus-mycomputer.desktop"
    assert copied.is_file()
    plasma = (profile / "payload/home/.config/plasma-org.kde.plasma.desktop-appletsrc").read_text(
        encoding="utf-8"
    )
    assert str(launcher) not in plasma
    assert "file://{{HOME}}/.local/share/applications/pardus-mycomputer.desktop" in plasma
    surface = manifest.restore["desktop_surface"]
    assert "{{HOME}}/.local/share/applications/pardus-mycomputer.desktop" in surface["applet_launchers"]
    assert verify_profile(profile).ok


def test_v0329_runtime_plasma_wallpaper_overrides_stale_disk_config(tmp_path: Path, monkeypatch):
    _patch_capture(monkeypatch)
    import linux_iso.capture as capture

    home = tmp_path / "home"
    config = home / ".config"
    wallpaper = home / "Resimler/ArkaPlanlar/dreamlike-whale.jpg"
    config.mkdir(parents=True)
    wallpaper.parent.mkdir(parents=True)
    wallpaper.write_bytes(b"whale")
    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][42]\n"
        "plugin=org.kde.plasma.folder\n"
        "wallpaperplugin=org.kde.image\n"
        "[Containments][42][Wallpaper][org.kde.image][General]\n"
        "Image=file:///usr/share/wallpapers/Next/contents/images/1920x1080.png\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        capture,
        "_runtime_plasma_wallpaper_state",
        lambda _home: [
            {
                "id": 42,
                "plugin": "org.kde.image",
                "image": f"file://{wallpaper}",
                "slidePaths": "",
            }
        ],
    )

    profile = tmp_path / "profile"
    capture_profile(profile, home)
    restored = (
        profile / "payload/home/.config/plasma-org.kde.plasma.desktop-appletsrc"
    ).read_text(encoding="utf-8")
    assert "wallpaperplugin=org.kde.image" in restored
    assert "Image=file://{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg" in restored
    assert "wallpapers/Next" not in restored
    assert (profile / "payload/home/Resimler/ArkaPlanlar/dreamlike-whale.jpg").is_file()
    assert verify_profile(profile).ok
