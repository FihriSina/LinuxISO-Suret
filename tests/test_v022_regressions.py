from __future__ import annotations

import json
from pathlib import Path

import yaml

from linux_iso.desktop.kde import component_locations
from linux_iso.packages.inventory import _categorize, _make, _native_visibility
from linux_iso.planner import audit


def test_native_package_false_positives_are_hidden():
    assert _categorize("amd64-microcode") == "other"
    assert _categorize("dmidecode") == "other"
    assert _categorize("code") == "development"
    assert _categorize("signal-desktop") == "communication"

    visible, reason, _ = _native_visibility("amd64-microcode", {})
    assert visible is False
    assert "hidden" in reason.lower()

    visible, _, _ = _native_visibility("python3.13-venv", {})
    assert visible is False

    assert _make("libfishcamp1t64", "apt").required_for_appearance is False
    assert _make("libkf6iconthemes-dev", "apt").required_for_appearance is False
    assert _make("kde-plasma-desktop", "apt").required_for_appearance is True


def test_kde_component_can_resolve_metadata_id(tmp_path: Path):
    home = tmp_path / "home"
    theme = home / ".local/share/plasma/look-and-feel/com.example.nordic"
    theme.mkdir(parents=True)
    (theme / "metadata.json").write_text(
        json.dumps({"KPlugin": {"Id": "Nordic", "Name": "Nordic Global Theme"}}),
        encoding="utf-8",
    )

    user_paths, _ = component_locations(home, "look-and-feel", "Nordic")
    assert theme in user_paths


def test_audit_groups_icon_theme_files(tmp_path: Path):
    profile = tmp_path / "profile"
    profile.mkdir()
    assets = [
        {
            "source": f"{{{{HOME}}}}/.local/share/icons/Tela-manjaro/16/panel/icon-{i}.svg",
            "destination": f"{{{{HOME}}}}/.local/share/icons/Tela-manjaro/16/panel/icon-{i}.svg",
            "kind": "desktop-asset",
        }
        for i in range(5)
    ]
    assets.append(
        {
            "source": "{{HOME}}/Pictures/custom.png",
            "destination": "{{HOME}}/Pictures/custom.png",
            "kind": "referenced-asset",
        }
    )
    manifest = {
        "source": {"distro_name": "Test"},
        "desktop": {
            "desktop": "kde-plasma",
            "custom_assets": assets,
            "widget_details": [],
            "component_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True, "excluded": [], "notes": []},
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    report = audit(profile)
    assert "icon-theme=Tela-manjaro: 5 files" in report
    assert "icon-0.svg" not in report
    assert "{{HOME}}/Pictures/custom.png" in report


def test_audit_groups_aurorae_window_decoration(tmp_path: Path):
    profile = tmp_path / "profile"
    profile.mkdir()
    assets = [
        {
            "source": f"{{{{HOME}}}}/.local/share/aurorae/themes/ChromeOS-dark/icon-{i}.svg",
            "destination": f"{{{{HOME}}}}/.local/share/aurorae/themes/ChromeOS-dark/icon-{i}.svg",
            "kind": "desktop-asset",
        }
        for i in range(4)
    ]
    manifest = {
        "source": {"distro_name": "Test"},
        "desktop": {
            "desktop": "kde-plasma",
            "custom_assets": assets,
            "widget_details": [],
            "component_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True, "excluded": [], "notes": []},
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    report = audit(profile)
    assert "window-decoration=ChromeOS-dark: 4 files" in report
    assert "icon-0.svg" not in report


def test_active_kde_components_detects_aurorae_decoration(tmp_path: Path):
    from linux_iso.desktop.kde import active_kde_components

    home = tmp_path / "home"
    config = home / ".config"
    config.mkdir(parents=True)
    (config / "kwinrc").write_text(
        "[org.kde.kdecoration2]\n"
        "theme=__aurorae__svg__ChromeOS-dark\n",
        encoding="utf-8",
    )

    components = active_kde_components(home)
    assert {"kind": "window-decoration", "name": "ChromeOS-dark"} in components


def test_component_locations_resolves_user_aurorae_theme(tmp_path: Path):
    home = tmp_path / "home"
    theme = home / ".local/share/aurorae/themes/ChromeOS-dark"
    theme.mkdir(parents=True)
    (theme / "metadata.json").write_text(
        json.dumps({"KPlugin": {"Id": "ChromeOS-dark", "Name": "ChromeOS Dark"}}),
        encoding="utf-8",
    )

    user_paths, _ = component_locations(home, "window-decoration", "ChromeOS-dark")
    assert theme in user_paths
