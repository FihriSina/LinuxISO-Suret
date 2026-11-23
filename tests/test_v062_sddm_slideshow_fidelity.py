from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml

import linux_iso.capture as capture
import linux_iso.builder.native as native
from linux_iso.models import CapturedFile
from linux_iso.verification import verify_profile


def _patch_minimal_capture(monkeypatch):
    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "6.test"))
    monkeypatch.setattr(
        capture,
        "collect_system_info",
        lambda: {
            "distro_id": "pardus",
            "distro_name": "Pardus Test",
            "distro_version": "25.2",
            "architecture": "x86_64",
        },
    )
    monkeypatch.setattr(capture, "collect_packages", lambda: [])
    monkeypatch.setattr(capture, "referenced_widgets", lambda _home: [])
    monkeypatch.setattr(capture, "user_plasmoids", lambda _home: [])
    monkeypatch.setattr(capture, "referenced_application_desktops", lambda _home: [])
    monkeypatch.setattr(capture, "active_kwin_user_components", lambda _home: [])
    monkeypatch.setattr(capture, "active_kde_components", lambda _home: [])
    monkeypatch.setattr(capture, "icon_theme_inheritance_chain", lambda _home, _name: [])
    monkeypatch.setattr(capture, "_runtime_plasma_wallpaper_state", lambda _home: [])


def test_v062_reads_sddm_config_in_real_precedence_order(tmp_path: Path):
    vendor = tmp_path / "usr/lib/sddm/sddm.conf.d"
    etc = tmp_path / "etc/sddm.conf.d"
    main = tmp_path / "etc/sddm.conf"
    vendor.mkdir(parents=True)
    etc.mkdir(parents=True)
    main.parent.mkdir(parents=True, exist_ok=True)
    (vendor / "10-vendor.conf").write_text("[Theme]\nCurrent=vendor\nCursorSize=20\n", encoding="utf-8")
    (etc / "kde_settings.conf").write_text("[Theme]\nCurrent=kde-store\nCursorSize=28\n", encoding="utf-8")
    main.write_text("[Theme]\nCurrent=user-winner\nCursorSize=32\n", encoding="utf-8")

    settings = capture._read_sddm_theme(vendor_confd=vendor, etc_confd=etc, main_config=main)

    assert settings["Current"] == "user-winner"
    assert settings["CursorSize"] == "32"


def test_v062_bundles_external_sddm_background_and_rewrites_theme_config(tmp_path: Path):
    home = tmp_path / "home"
    background = home / "Resimler/Login/login-bg.jpg"
    background.parent.mkdir(parents=True)
    background.write_bytes(b"custom-sddm-background")

    theme = tmp_path / "usr/share/sddm/themes/store-theme"
    theme.mkdir(parents=True)
    (theme / "Main.qml").write_text("// qml\n", encoding="utf-8")
    (theme / "theme.conf").write_text("[General]\nbackground=default.jpg\n", encoding="utf-8")
    (theme / "default.jpg").write_bytes(b"default")
    (theme / "theme.conf.user").write_text(
        f"[General]\nbackground={background}\n",
        encoding="utf-8",
    )

    captured = tmp_path / "profile/payload/system/sddm/theme"
    assert capture._copy_visual_tree(theme, captured)
    bundled = capture._bundle_sddm_external_assets(theme, captured, home)

    user_config = (captured / "theme.conf.user").read_text(encoding="utf-8")
    assert str(home) not in user_config
    assert "background=suret-assets/" in user_config
    assert len(bundled) == 1
    assert (captured / bundled[0]).read_bytes() == b"custom-sddm-background"


def test_v062_capture_profile_records_self_contained_sddm_theme(tmp_path: Path, monkeypatch):
    _patch_minimal_capture(monkeypatch)
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / ".config/plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1]\nplugin=org.kde.plasma.folder\n",
        encoding="utf-8",
    )
    background = home / "Resimler/login.png"
    background.parent.mkdir(parents=True)
    background.write_bytes(b"login")
    theme = tmp_path / "theme-store/fancy"
    theme.mkdir(parents=True)
    (theme / "Main.qml").write_text("// qml\n", encoding="utf-8")
    (theme / "theme.conf.user").write_text(
        f"[General]\nbackground={background}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        capture,
        "_read_sddm_theme",
        lambda: {"Current": "fancy", "CursorTheme": "Breeze", "CursorSize": "24"},
    )
    monkeypatch.setattr(capture, "_sddm_theme_candidates", lambda _settings: [theme])

    profile = tmp_path / "profile"
    manifest = capture.capture_profile(profile, home)

    sddm = manifest.restore["system_visual"]["sddm"]
    assert sddm["theme_captured"] is True
    assert sddm["source_theme"] == "fancy"
    assert len(sddm["external_assets"]) == 1
    captured_user = (profile / "payload/system/sddm/theme/theme.conf.user").read_text(encoding="utf-8")
    assert str(home) not in captured_user
    assert "suret-assets/" in captured_user
    assert verify_profile(profile).ok


def test_v062_internal_theme_symlink_is_dereferenced_but_external_symlink_is_not(tmp_path: Path):
    theme = tmp_path / "theme"
    theme.mkdir()
    (theme / "Main.qml").write_text("// qml\n", encoding="utf-8")
    (theme / "real.png").write_bytes(b"inside")
    (theme / "inside.png").symlink_to("real.png")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    (theme / "outside.png").symlink_to(outside)

    target = tmp_path / "captured"
    assert capture._copy_visual_tree(theme, target)
    assert (target / "inside.png").read_bytes() == b"inside"
    assert (target / "real.png").read_bytes() == b"inside"
    assert not (target / "outside.png").exists()


def test_v062_sddm_metadata_custom_config_file_is_scanned_for_external_background(tmp_path: Path):
    home = tmp_path / "home"
    background = home / "Pictures/login.webp"
    background.parent.mkdir(parents=True)
    background.write_bytes(b"webp")
    theme = tmp_path / "theme"
    theme.mkdir()
    (theme / "Main.qml").write_text("// qml\n", encoding="utf-8")
    (theme / "metadata.desktop").write_text(
        "[SddmGreeterTheme]\nConfigFile=appearance.ini\n",
        encoding="utf-8",
    )
    (theme / "appearance.ini.user").write_text(
        f"[General]\nBackground={background}\n",
        encoding="utf-8",
    )
    captured = tmp_path / "captured"
    assert capture._copy_visual_tree(theme, captured)

    bundled = capture._bundle_sddm_external_assets(theme, captured, home)

    text = (captured / "appearance.ini.user").read_text(encoding="utf-8")
    assert "Background=suret-assets/" in text
    assert len(bundled) == 1


def test_v062_runtime_slideshow_state_keeps_slideshow_plugin(tmp_path: Path):
    home = tmp_path / "home"
    slides = home / "Resimler/Slayt"
    slides.mkdir(parents=True)
    current = slides / "current.jpg"
    current.write_bytes(b"slide")
    payload = tmp_path / "payload"
    config = payload / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    config.parent.mkdir(parents=True)
    config.write_text(
        "[Containments][7]\n"
        "wallpaperplugin=org.kde.image\n"
        "[Containments][7][Wallpaper][org.kde.image][General]\n"
        "Image=file:///usr/share/wallpapers/default.jpg\n"
        "SlidePaths=file:///tmp/stale\n"
        "SlideTimer=120\n",
        encoding="utf-8",
    )
    captured = [
        CapturedFile(
            source="{{HOME}}/.config/plasma-org.kde.plasma.desktop-appletsrc",
            destination="{{HOME}}/.config/plasma-org.kde.plasma.desktop-appletsrc",
            kind="config",
            sha256="old",
        )
    ]

    capture._apply_runtime_wallpaper_state(
        payload,
        home,
        [
            {
                "id": 7,
                "screen": 0,
                "plugin": "org.kde.slideshow",
                "image": f"file://{current}",
                "slidePaths": f"file://{slides}",
            }
        ],
        {},
        captured,
    )

    text = config.read_text(encoding="utf-8")
    assert "wallpaperplugin=org.kde.slideshow" in text
    assert "[Wallpaper][org.kde.slideshow][General]" in text
    assert "Image=file://{{HOME}}/Resimler/Slayt/current.jpg" in text
    assert "SlidePaths=file://{{HOME}}/Resimler/Slayt" in text
    assert "SlideTimer=120" in text
    assert "[Wallpaper][org.kde.image][General]" not in text


def test_v062_native_system_visual_is_fail_closed_and_neutralizes_theme_overrides():
    script = native.NATIVE_SYSTEM_VISUAL
    build = native.NATIVE_BUILD_SCRIPT
    assert "neutralize_sddm_theme_overrides" in script
    assert "10-suret-source-theme.conf" in script
    assert 'sddm_lines.append("ThemeDir=/usr/share/sddm/themes")' in script
    assert 'keys = {"Current", "CursorTheme", "CursorSize", "Font", "ThemeDir"}' in script
    assert "restored SDDM theme is missing Main.qml" in script
    assert "exit 35" in build
    assert "continuing for diagnostics" not in build


def test_v062_stage_refuses_real_legacy_profile_that_lost_slideshow_intent(tmp_path: Path, monkeypatch):
    profile = tmp_path / "profile"
    (profile / "payload/home").mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "distro_version": "25.2", "architecture": "x86_64"},
        "desktop": {"desktop": "kde-plasma", "configs": [], "custom_assets": []},
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "profile_version": "0.6.1",
            "fidelity_schema": 10,
        },
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    base = tmp_path / "Pardus-25.2.iso"
    base.write_bytes(b"iso")

    monkeypatch.setattr(native, "verify_profile", lambda _path: SimpleNamespace(ok=True))
    monkeypatch.setattr(
        native,
        "probe_native_iso",
        lambda _path: native.NativeIsoProbe(
            base_iso=str(base),
            distro_id="pardus",
            distro_name="Pardus",
            distro_version="25.2",
            architecture="x86_64",
            package_family="apt",
            live_rootfs="/live/filesystem.squashfs",
            kernel="/live/vmlinuz",
            initrd="/live/initrd.img",
            installer="pardus-installer",
            supports_native_build=True,
        ),
    )

    try:
        native.stage_native_project(profile, base, tmp_path / "build")
    except native.NativeIsoError as exc:
        assert "appearance/SDDM/slideshow fidelity schema" in str(exc)
    else:
        raise AssertionError("legacy real profile should require a one-time recapture")


def test_v062_retry_detects_legacy_profile_before_resetting_build_tree():
    retry = Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    assert "fidelity < 12" in retry
    assert "native-acceptance.sh BASE_ISO once" in retry
    assert retry.index("fidelity < 12") < retry.index('phase "Resetting previous Native build state"')
