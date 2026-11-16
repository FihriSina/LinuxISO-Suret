from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.capture import capture_profile
from linux_iso.verification import verify_profile


def test_unresolved_inherited_icon_theme_is_recorded_as_warning_source(tmp_path: Path, monkeypatch):
    import linux_iso.capture as capture

    home = tmp_path / "home"
    config = home / ".config"
    icons = home / ".local/share/icons/ActiveIcons"
    config.mkdir(parents=True)
    icons.mkdir(parents=True)

    (config / "kdeglobals").write_text("[Icons]\nTheme=ActiveIcons\n", encoding="utf-8")
    (icons / "index.theme").write_text(
        "[Icon Theme]\nName=Active Icons\nInherits=MissingLegacyFallback\n",
        encoding="utf-8",
    )
    (icons / "active.svg").write_text("<svg/>", encoding="utf-8")

    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "Plasma test"))
    monkeypatch.setattr(capture, "collect_system_info", lambda: {"distro_id": "test", "distro_name": "Test"})
    monkeypatch.setattr(capture, "collect_packages", lambda: [])

    profile = tmp_path / "profile"
    manifest = capture_profile(profile, home, asset_mode="active")
    detail = next(
        item for item in manifest.desktop.component_details
        if item.get("name") == "MissingLegacyFallback"
    )

    assert detail["source"] == "missing-inherited-fallback"
    assert detail["inherited"] is True
    assert detail["inherited_from"] == "ActiveIcons"

    result = verify_profile(profile)
    assert result.ok is True
    assert any("Inherited icon fallback" in warning for warning in result.warnings)


def test_direct_unresolved_icon_theme_remains_fatal(tmp_path: Path):
    profile = tmp_path / "profile"
    (profile / "payload/home").mkdir(parents=True)
    manifest = {
        "desktop": {
            "configs": [],
            "custom_assets": [],
            "widget_details": [],
            "component_details": [
                {
                    "kind": "icon-theme",
                    "name": "MissingDirectTheme",
                    "source": "not-found",
                    "bundled": False,
                }
            ],
        },
        "packages": [],
        "restore": {"home_placeholder": "{{HOME}}", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    result = verify_profile(profile)
    assert result.ok is False
    assert any("MissingDirectTheme" in error for error in result.errors)


def test_legacy_profile_unresolved_inherited_icon_is_backward_compatible_warning(tmp_path: Path):
    profile = tmp_path / "legacy-profile"
    (profile / "payload/home").mkdir(parents=True)
    manifest = {
        "desktop": {
            "configs": [],
            "custom_assets": [],
            "widget_details": [],
            "component_details": [
                {
                    "kind": "icon-theme",
                    "name": "AdwaitaLegacy",
                    "source": "not-found",
                    "bundled": False,
                    "inherited": True,
                    "inherited_from": "Tela-manjaro-dark",
                }
            ],
        },
        "packages": [],
        "restore": {"home_placeholder": "{{HOME}}", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    result = verify_profile(profile)
    assert result.ok is True
    assert any("AdwaitaLegacy" in warning for warning in result.warnings)
    assert "PASS WITH WARNINGS" in result.render()
