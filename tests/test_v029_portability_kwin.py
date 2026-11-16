from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.capture import capture_profile
from linux_iso.portability import portability_report


def _base_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    config = home / ".config"
    icons = home / ".local/share/icons/TestIcons"
    config.mkdir(parents=True)
    icons.mkdir(parents=True)
    (config / "kdeglobals").write_text("[Icons]\nTheme=TestIcons\n", encoding="utf-8")
    (icons / "index.theme").write_text("[Icon Theme]\nName=TestIcons\n", encoding="utf-8")
    (icons / "icon.svg").write_text("<svg/>", encoding="utf-8")
    return home


def test_active_only_captures_only_enabled_user_kwin_plugins(tmp_path: Path, monkeypatch):
    import linux_iso.capture as capture

    home = _base_home(tmp_path)
    scripts = home / ".local/share/kwin/scripts"
    enabled = scripts / "enabled-script"
    disabled = scripts / "disabled-script"
    for path in (enabled, disabled):
        path.mkdir(parents=True)
        (path / "metadata.json").write_text(
            '{"KPlugin":{"Id":"' + path.name + '"},"KPackageStructure":"KWin/Script"}',
            encoding="utf-8",
        )
        (path / "main.js").write_text("// test", encoding="utf-8")
    (home / ".config/kwinrc").write_text(
        "[Plugins]\nenabled-scriptEnabled=true\ndisabled-scriptEnabled=false\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "Plasma 6"))
    monkeypatch.setattr(capture, "collect_system_info", lambda: {"distro_id": "ubuntu", "distro_name": "Ubuntu", "architecture": "x86_64"})
    monkeypatch.setattr(capture, "collect_packages", lambda: [])

    manifest = capture_profile(tmp_path / "profile", home, asset_mode="active")
    destinations = {item.destination for item in manifest.desktop.custom_assets}
    assert any("/kwin/scripts/enabled-script/" in item for item in destinations)
    assert not any("/kwin/scripts/disabled-script/" in item for item in destinations)
    assert any(
        item.get("kind") == "kwin-script" and item.get("name") == "enabled-script"
        for item in manifest.desktop.component_details
    )


def test_user_plasmoid_records_qml_runtime_hints(tmp_path: Path, monkeypatch):
    import linux_iso.capture as capture

    home = _base_home(tmp_path)
    plasmoid = home / ".local/share/plasma/plasmoids/com.example.widget"
    (plasmoid / "contents/ui").mkdir(parents=True)
    (plasmoid / "metadata.json").write_text(
        '{"KPlugin":{"Id":"com.example.widget","Version":"2"},'
        '"KPackageStructure":"Plasma/Applet","X-Plasma-API-Minimum-Version":"6.0"}',
        encoding="utf-8",
    )
    (plasmoid / "contents/ui/main.qml").write_text(
        "import QtQuick\nimport org.kde.plasma.plasmoid\nimport Fancy.Runtime\nItem {}\n",
        encoding="utf-8",
    )
    (home / ".config/plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1][Applets][2]\nplugin=com.example.widget\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "Plasma 6"))
    monkeypatch.setattr(capture, "collect_system_info", lambda: {"distro_id": "ubuntu", "distro_name": "Ubuntu", "architecture": "x86_64"})
    monkeypatch.setattr(capture, "collect_packages", lambda: [])

    manifest = capture_profile(tmp_path / "profile", home, asset_mode="active")
    detail = next(item for item in manifest.desktop.widget_details if item.get("id") == "com.example.widget")
    assert detail["plasma_api_minimum_version"] == "6.0"
    assert "Fancy.Runtime" in detail["external_qml_imports"]
    assert "QtQuick" in detail["qml_imports"]


def test_portability_warns_for_external_widget_runtime(tmp_path: Path):
    profile = tmp_path / "profile"
    (profile / "payload/home").mkdir(parents=True)
    manifest = {
        "source": {"distro_name": "Ubuntu", "architecture": "x86_64"},
        "desktop": {
            "configs": [],
            "custom_assets": [],
            "widget_details": [
                {
                    "id": "com.example.widget",
                    "source": "user-local",
                    "bundled": False,
                    "external_qml_imports": ["Fancy.Runtime"],
                    "plasma_api_minimum_version": "6.0",
                }
            ],
            "component_details": [],
        },
        "packages": [],
        "restore": {"home_placeholder": "{{HOME}}", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    result = portability_report(profile)
    assert result.ready is True
    assert any("Fancy.Runtime" in item for item in result.warnings)
    assert "READY WITH WARNINGS" in result.render()
