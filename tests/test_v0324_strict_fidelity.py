from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import yaml

from linux_iso.builder.kiwi import generate_kiwi_project
from linux_iso.capture import capture_profile
from linux_iso.models import Package


def test_v0324_capture_bundles_system_theme_and_external_wallpaper(tmp_path: Path, monkeypatch):
    import linux_iso.capture as capture

    home = tmp_path / "home"
    config = home / ".config"
    config.mkdir(parents=True)

    external_dir = tmp_path / "external assets"
    external_dir.mkdir()
    wallpaper = external_dir / "whale sky.png"
    wallpaper.write_bytes(b"not-a-real-png-but-a-capture-fixture")

    (config / "kdeglobals").write_text(
        "[Icons]\nTheme=SourceTheme\n",
        encoding="utf-8",
    )
    encoded_wallpaper = quote(str(wallpaper), safe="/")
    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        f"[Containments][1][Wallpaper][org.kde.image][General]\nImage=file://{encoded_wallpaper}\n",
        encoding="utf-8",
    )

    system_theme = tmp_path / "system-theme" / "SourceTheme"
    system_theme.mkdir(parents=True)
    (system_theme / "index.theme").write_text(
        "[Icon Theme]\nName=SourceTheme\n",
        encoding="utf-8",
    )
    (system_theme / "apps.svg").write_text("<svg/>", encoding="utf-8")

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
    monkeypatch.setattr(
        capture,
        "active_kde_components",
        lambda _home: [{"kind": "icon-theme", "name": "SourceTheme"}],
    )
    monkeypatch.setattr(capture, "icon_theme_inheritance_chain", lambda _home, _name: [])
    monkeypatch.setattr(
        capture,
        "component_locations",
        lambda _home, kind, name: (
            [],
            [(system_theme, Path(".local/share/icons/SourceTheme"))]
            if (kind, name) == ("icon-theme", "SourceTheme")
            else [],
        ),
    )
    monkeypatch.setattr(capture, "package_owner", lambda _path: ("apt", "source-theme"))

    output = tmp_path / "profile"
    manifest = capture_profile(output, home)

    assert (output / "payload/home/.local/share/icons/SourceTheme/index.theme").is_file()
    assert (output / "payload/home/.local/share/icons/SourceTheme/apps.svg").is_file()
    detail = manifest.desktop.component_details[0]
    assert detail["source"] == "system-package"
    assert detail["bundled"] is True
    assert detail["bundle_root"] == "{{HOME}}/.local/share/icons/SourceTheme"

    required = {(p.provider, p.name) for p in manifest.packages if p.required_for_appearance}
    assert ("apt", "source-theme") in required

    captured_config = (
        output / "payload/home/.config/plasma-org.kde.plasma.desktop-appletsrc"
    ).read_text(encoding="utf-8")
    assert str(wallpaper) not in captured_config
    assert "{{HOME}}/.local/share/linux-iso/captured-assets/" in captured_config
    captured_external = list(
        (output / "payload/home/.local/share/linux-iso/captured-assets").glob("*-whale sky.png")
    )
    assert len(captured_external) == 1
    assert captured_external[0].read_bytes() == wallpaper.read_bytes()
    assert manifest.restore["fidelity_schema"] == 9


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    config = payload / "kdeglobals"
    config.write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "architecture": "x86_64"},
        "desktop": {
            "desktop": "kde-plasma",
            "configs": [
                {
                    "source": "{{HOME}}/.config/kdeglobals",
                    "destination": "{{HOME}}/.config/kdeglobals",
                    "kind": "config",
                }
            ],
            "custom_assets": [],
        },
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "asset_mode": "active",
            "fidelity_schema": 2,
        },
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return profile


def test_v0324_live_and_target_profile_application_clear_kubuntu_defaults(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)

    live = (build / "root/usr/lib/linux-iso/apply-live-profile.py").read_text(encoding="utf-8")
    target = (
        build / "root/usr/share/linux-iso/calamares/modules/linuxiso-install/main.py"
    ).read_text(encoding="utf-8")

    for script in (live, target):
        assert '"Desktop"' in script
        assert '".config/plasma-org.kde.plasma.desktop-appletsrc"' in script
        assert '".local/share/icons"' in script
        assert "rmtree" in script

    assert "profile-applied" in live
    assert "profile-applied" in target


def test_v0324_runtime_patcher_rebrands_kubuntu_installer_text(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    patcher = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text(
        encoding="utf-8"
    )
    assert "patch_branding_text" in patcher
    assert 'replace("Kubuntu", "Linux ISO - Suret")' in patcher


def test_v0324_safe_build_rejects_pre_fidelity_profile():
    script = Path("scripts/safe-first-iso.sh").read_text(encoding="utf-8")
    assert "fidelity_schema" in script
    assert "Profile predates first-login convergence fidelity capture v9" in script
    assert "uv run linux-iso scan -o" in script
