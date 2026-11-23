from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.capture import capture_profile
from linux_iso.verification import verify_profile


def test_active_only_capture_preserves_visible_icon_library_but_prunes_unused_plasmoid(tmp_path: Path, monkeypatch):
    import linux_iso.capture as capture

    home = tmp_path / "home"
    config = home / ".config"
    active_icons = home / ".local/share/icons/ActiveIcons"
    base_icons = home / ".local/share/icons/BaseIcons"
    unused_icons = home / ".local/share/icons/UnusedIcons"
    used_widget = home / ".local/share/plasma/plasmoids/UsedWidget"
    unused_widget = home / ".local/share/plasma/plasmoids/UnusedWidget"

    for path in (config, active_icons, base_icons, unused_icons, used_widget, unused_widget):
        path.mkdir(parents=True, exist_ok=True)

    (config / "kdeglobals").write_text("[Icons]\nTheme=ActiveIcons\n", encoding="utf-8")
    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1][Applets][2]\nplugin=UsedWidget\n", encoding="utf-8"
    )
    (active_icons / "index.theme").write_text(
        "[Icon Theme]\nName=Active Icons\nInherits=BaseIcons,hicolor\n", encoding="utf-8"
    )
    (active_icons / "active.svg").write_text("<svg/>", encoding="utf-8")
    (base_icons / "index.theme").write_text("[Icon Theme]\nName=Base Icons\n", encoding="utf-8")
    (base_icons / "base.svg").write_text("<svg/>", encoding="utf-8")
    (unused_icons / "index.theme").write_text("[Icon Theme]\nName=Unused Icons\n", encoding="utf-8")
    (unused_icons / "unused.svg").write_text("<svg/>", encoding="utf-8")
    (used_widget / "metadata.json").write_text('{"KPlugin":{"Id":"UsedWidget"}}', encoding="utf-8")
    (used_widget / "main.qml").write_text("Item {}", encoding="utf-8")
    (unused_widget / "metadata.json").write_text('{"KPlugin":{"Id":"UnusedWidget"}}', encoding="utf-8")

    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "Plasma test"))
    monkeypatch.setattr(capture, "collect_system_info", lambda: {"distro_id": "test", "distro_name": "Test"})
    monkeypatch.setattr(capture, "collect_packages", lambda: [])

    profile = tmp_path / "profile"
    manifest = capture_profile(profile, home, asset_mode="active")
    destinations = {item.destination for item in manifest.desktop.custom_assets}

    assert any("/.local/share/icons/ActiveIcons/" in item for item in destinations)
    assert any("/.local/share/icons/BaseIcons/" in item for item in destinations)
    assert any("/.local/share/icons/UnusedIcons/" in item for item in destinations)
    assert any("/.local/share/plasma/plasmoids/UsedWidget/" in item for item in destinations)
    assert not any("/.local/share/plasma/plasmoids/UnusedWidget/" in item for item in destinations)
    assert manifest.restore["asset_mode"] == "active"


def _minimal_verified_profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    target = payload / "kdeglobals"
    target.write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")

    from linux_iso.assets import sha256_file

    manifest = {
        "source": {"distro_name": "Test"},
        "desktop": {
            "desktop": "kde-plasma",
            "configs": [
                {
                    "source": "{{HOME}}/.config/kdeglobals",
                    "destination": "{{HOME}}/.config/kdeglobals",
                    "kind": "config",
                    "sha256": sha256_file(target),
                }
            ],
            "custom_assets": [],
            "widget_details": [],
            "component_details": [
                {
                    "kind": "look-and-feel",
                    "name": "LegacyTheme",
                    "source": "missing-meta-package",
                    "bundled": False,
                }
            ],
        },
        "packages": [],
        "security": {"safe_mode": True, "notes": []},
        "restore": {"home_placeholder": "{{HOME}}", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return profile


def test_verify_profile_passes_with_meta_theme_warning(tmp_path: Path):
    profile = _minimal_verified_profile(tmp_path)
    result = verify_profile(profile)
    assert result.ok is True
    assert result.errors == []
    assert any("meta-package" in item for item in result.warnings)
    assert "PASS WITH WARNINGS" in result.render()


def test_verify_profile_detects_tampered_payload(tmp_path: Path):
    profile = _minimal_verified_profile(tmp_path)
    (profile / "payload/home/.config/kdeglobals").write_text("tampered", encoding="utf-8")
    result = verify_profile(profile)
    assert result.ok is False
    assert any("Checksum mismatch" in item for item in result.errors)
    assert "Status: FAIL" in result.render()


def test_all_asset_mode_keeps_unused_theme(tmp_path: Path, monkeypatch):
    import linux_iso.capture as capture

    home = tmp_path / "home-all"
    config = home / ".config"
    unused_icons = home / ".local/share/icons/UnusedIcons"
    config.mkdir(parents=True)
    unused_icons.mkdir(parents=True)
    (config / "kdeglobals").write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")
    (unused_icons / "index.theme").write_text("[Icon Theme]\nName=Unused Icons\n", encoding="utf-8")
    (unused_icons / "unused.svg").write_text("<svg/>", encoding="utf-8")

    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "Plasma test"))
    monkeypatch.setattr(capture, "collect_system_info", lambda: {"distro_id": "test", "distro_name": "Test"})
    monkeypatch.setattr(capture, "collect_packages", lambda: [])
    monkeypatch.setattr(capture, "system_plasmoid", lambda _plugin: None)

    profile = tmp_path / "profile-all"
    manifest = capture_profile(profile, home, asset_mode="all")
    assert any("/.local/share/icons/UnusedIcons/" in item.destination for item in manifest.desktop.custom_assets)
    assert manifest.restore["asset_mode"] == "all"


def test_stage_iso_rejects_failed_profile_verification(tmp_path: Path):
    from linux_iso.builder.kiwi import BuilderError, generate_kiwi_project

    profile = _minimal_verified_profile(tmp_path)
    (profile / "payload/home/.config/kdeglobals").write_text("tampered", encoding="utf-8")

    try:
        generate_kiwi_project(profile, tmp_path / "build")
    except BuilderError as exc:
        assert "Profile verification failed" in str(exc)
    else:
        raise AssertionError("staging should reject a profile with a bad checksum")
