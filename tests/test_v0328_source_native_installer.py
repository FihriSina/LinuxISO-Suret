from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.builder.calamares import generate_calamares_overlay
from linux_iso.installer.catalog import build_catalog
import linux_iso.system as system


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home"
    config = payload / ".config"
    apps = payload / ".local/share/applications"
    icons = payload / ".local/share/icons/hicolor/scalable/apps"
    config.mkdir(parents=True)
    apps.mkdir(parents=True)
    icons.mkdir(parents=True)

    wallpaper = payload / "Resimler/ArkaPlanlar/dreamlike-whale.jpg"
    wallpaper.parent.mkdir(parents=True)
    wallpaper.write_bytes(b"wallpaper-fixture")
    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1][Wallpaper][org.kde.image][General]\n"
        "Image=file://{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg\n",
        encoding="utf-8",
    )
    (apps / "firefox.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Firefox\nExec=firefox\nIcon=firefox\n",
        encoding="utf-8",
    )
    (icons / "firefox.svg").write_text("<svg/>", encoding="utf-8")
    branding = profile / "branding"
    branding.mkdir(parents=True)
    (branding / "source-logo.svg").write_text("<svg><title>Pardus</title></svg>", encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "source": {
            "distro_id": "pardus",
            "distro_name": "Pardus GNU/Linux 25",
            "distro_name_short": "Pardus GNU/Linux",
            "distro_version": "25",
            "distro_home_url": "https://pardus.org.tr/",
            "branding_logo": "branding/source-logo.svg",
            "architecture": "x86_64",
        },
        "desktop": {"desktop": "kde-plasma", "configs": [], "custom_assets": []},
        "packages": [
            {
                "name": "firefox",
                "provider": "apt",
                "category": "internet",
                "required_for_appearance": False,
                "installer_visible": True,
            }
        ],
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "fidelity_schema": 7,
        },
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return profile


def test_v0328_system_info_keeps_source_branding_metadata(monkeypatch):
    monkeypatch.setattr(
        system,
        "parse_os_release",
        lambda: {
            "ID": "pardus",
            "PRETTY_NAME": "Pardus GNU/Linux 25",
            "NAME": "Pardus GNU/Linux",
            "VERSION_ID": "25",
            "LOGO": "pardus",
            "ANSI_COLOR": "1;34",
            "HOME_URL": "https://pardus.org.tr/",
            "SUPPORT_URL": "https://pardus.org.tr/destek/",
        },
    )
    monkeypatch.setattr(system.platform, "release", lambda: "test-kernel")
    monkeypatch.setattr(system.platform, "machine", lambda: "x86_64")
    info = system.collect_system_info()
    assert info["distro_logo"] == "pardus"
    assert info["distro_name_short"] == "Pardus GNU/Linux"
    assert info["distro_home_url"].startswith("https://pardus")


def test_v0328_source_branding_and_visual_app_cards(tmp_path: Path):
    profile = _profile(tmp_path)
    overlay = tmp_path / "overlay"
    integration = generate_calamares_overlay(profile, overlay)

    assert integration["branding"] == "linuxiso-source"
    branding_dir = overlay / "etc/calamares/branding/linuxiso-source"
    desc = yaml.safe_load((branding_dir / "branding.desc").read_text(encoding="utf-8"))
    assert desc["strings"]["productName"] == "Pardus"
    assert desc["strings"]["versionedName"] == "Pardus GNU/Linux 25"
    assert desc["style"]["SidebarBackground"] == "#10242F"
    assert (branding_dir / "source-logo.svg").is_file()
    assert (branding_dir / "source-wallpaper.jpg").is_file()
    assert "Kubuntu" not in (branding_dir / "branding.desc").read_text(encoding="utf-8")

    conf_path = overlay / "etc/calamares/modules/packagechooserq-linuxiso_internet.conf"
    conf = yaml.safe_load(conf_path.read_text(encoding="utf-8"))
    assert conf["method"] == "legacy"
    assert conf["qmlFilename"] == "/etc/calamares/linuxiso-app-qml/linuxiso_internet.qml"
    assert conf["packageChoice"]
    qml = (overlay / "etc/calamares/linuxiso-app-qml/linuxiso_internet.qml").read_text(
        encoding="utf-8"
    )
    assert "Firefox" in qml
    assert "CheckBox" in qml
    assert "checked: true" in qml
    assert "file:///etc/calamares/linuxiso-app-cards/" in qml
    assert 'width: Math.max(280, root.width - 50)' in qml
    assert 'color: "#171D23"' in qml
    assert 'palette.text: "#FFFFFF"' in qml
    assert list((overlay / "etc/calamares/linuxiso-app-cards").glob("*-icon.svg"))


def test_v0328_catalog_has_human_facing_app_presentation(tmp_path: Path):
    catalog = build_catalog(_profile(tmp_path))
    item = catalog["categories"][0]["items"][0]
    assert item["display_name"] == "Firefox"
    assert "browser" in item["description"].lower()


def test_v0328_capture_source_logo_snapshot(tmp_path: Path, monkeypatch):
    import linux_iso.capture as capture

    source_logo = tmp_path / "pardus-logo.svg"
    source_logo.write_text("<svg><title>Pardus source logo</title></svg>", encoding="utf-8")
    monkeypatch.setattr(capture, "_source_brand_logo_candidates", lambda _source: [source_logo])
    profile = tmp_path / "profile-brand"
    profile.mkdir()
    result = capture._capture_source_branding(
        profile,
        {"distro_id": "pardus", "distro_logo": "pardus", "distro_name": "Pardus GNU/Linux 25"},
    )
    assert result["branding_logo"] == "branding/source-logo.svg"
    assert (profile / "branding/source-logo.svg").read_text(encoding="utf-8").startswith("<svg>")
