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
    monkeypatch.setattr(capture, "referenced_application_desktops", lambda _home: [])
    monkeypatch.setattr(capture, "active_kwin_user_components", lambda _home: [])
    monkeypatch.setattr(capture, "active_kde_components", lambda _home: [])
    monkeypatch.setattr(capture, "icon_theme_inheritance_chain", lambda _home, _name: [])


def test_v0326_repairs_wallpaper_moved_into_subdirectory(tmp_path: Path, monkeypatch):
    _patch_capture(monkeypatch)
    home = tmp_path / "home"
    config = home / ".config"
    pictures = home / "Resimler"
    moved_dir = pictures / "ArkaPlanlar"
    config.mkdir(parents=True)
    moved_dir.mkdir(parents=True)

    moved = moved_dir / "WallpaperHDForest.jpg"
    moved.write_bytes(b"wallpaper")
    stale = pictures / "WallpaperHDForest.jpg"

    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1][Wallpaper][org.kde.image][General]\n"
        f"Image=file://{stale}\n"
        f"SlidePaths=file://{moved_dir}\n",
        encoding="utf-8",
    )

    profile = tmp_path / "profile"
    manifest = capture_profile(profile, home)

    assert manifest.restore["fidelity_schema"] == 9
    restored = (
        profile / "payload/home/.config/plasma-org.kde.plasma.desktop-appletsrc"
    ).read_text(encoding="utf-8")
    assert str(stale) not in restored
    assert "{{HOME}}/Resimler/ArkaPlanlar/WallpaperHDForest.jpg" in restored
    assert (profile / "payload/home/Resimler/ArkaPlanlar/WallpaperHDForest.jpg").is_file()
    assert verify_profile(profile).ok


def test_v0326_does_not_guess_ambiguous_moved_wallpaper(tmp_path: Path, monkeypatch):
    _patch_capture(monkeypatch)
    home = tmp_path / "home"
    config = home / ".config"
    pictures = home / "Resimler"
    config.mkdir(parents=True)
    (pictures / "A").mkdir(parents=True)
    (pictures / "B").mkdir(parents=True)
    (pictures / "A/Wallpaper4kForest.jpg").write_bytes(b"a")
    (pictures / "B/Wallpaper4kForest.jpg").write_bytes(b"b")
    stale = pictures / "Wallpaper4kForest.jpg"

    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1][Wallpaper][org.kde.image][General]\n"
        f"Image=file://{stale}\n",
        encoding="utf-8",
    )

    profile = tmp_path / "profile"
    capture_profile(profile, home)
    result = verify_profile(profile)
    assert not result.ok
    assert any("Wallpaper reference has no payload asset" in error for error in result.errors)
