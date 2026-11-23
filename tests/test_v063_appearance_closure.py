from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml

import linux_iso.capture as capture
import linux_iso.builder.native as native
from linux_iso import __version__
from linux_iso.verification import verify_profile


def _probe(base: Path) -> native.NativeIsoProbe:
    return native.NativeIsoProbe(
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
    )


def _manifest(schema: int, *, icon: str = "Tela-manjaro-dark") -> dict:
    return {
        "schema_version": 1,
        "source": {
            "distro_id": "pardus",
            "distro_name": "Pardus",
            "distro_version": "25.2",
            "architecture": "x86_64",
        },
        "desktop": {
            "desktop": "kde-plasma",
            "configs": [],
            "custom_assets": [],
            "component_details": [
                {
                    "kind": "icon-theme",
                    "name": icon,
                    "source": "user-local",
                    "bundled": True,
                    "bundle_root": f"{{{{HOME}}}}/.local/share/icons/{icon}",
                },
                {
                    "kind": "color-scheme",
                    "name": "Nordic",
                    "source": "user-local",
                    "bundled": True,
                    "bundle_root": "{{HOME}}/.local/share/color-schemes/Nordic.colors",
                },
                {
                    "kind": "plasma-theme",
                    "name": "Nordic",
                    "source": "user-local",
                    "bundled": True,
                    "bundle_root": "{{HOME}}/.local/share/plasma/desktoptheme/Nordic",
                },
            ],
            "widget_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "profile_version": "0.6.5",
            "asset_mode": "active",
            "fidelity_schema": schema,
            "slideshow": {
                "active": True,
                "paths": ["{{HOME}}/Pictures/Slides"],
                "containments": 1,
                "entries": [
                    {
                        "containment_id": 7,
                        "screen": 0,
                        "plugin": "org.kde.slideshow",
                        "paths": ["{{HOME}}/Pictures/Slides"],
                        "settings": {
                            "SlidePaths": "file://{{HOME}}/Pictures/Slides",
                            "SlideTimer": "300",
                            "Randomize": "true",
                        },
                    }
                ],
            },
            "system_visual": {
                "sddm": {
                    "theme_captured": True,
                    "source_theme": "store-theme",
                    "external_assets": ["suret-assets/login.jpg"],
                }
            },
        },
    }


def test_v063_active_icon_theme_dereferences_safe_sibling_symlinks(tmp_path: Path):
    home = tmp_path / "home"
    icons = home / ".local/share/icons"
    base = icons / "Tela"
    active = icons / "Tela-manjaro-dark"
    base.mkdir(parents=True)
    active.mkdir(parents=True)
    (base / "base.svg").write_text("<svg>base</svg>", encoding="utf-8")
    (active / "index.theme").write_text(
        "[Icon Theme]\nName=Tela manjaro dark\nInherits=Tela\n", encoding="utf-8"
    )
    (active / "folder.svg").symlink_to("../Tela/base.svg")
    (active / "scalable").symlink_to("../Tela")
    outside = tmp_path / "private.txt"
    outside.write_text("must-not-copy", encoding="utf-8")
    (active / "escape.svg").symlink_to(outside)

    payload = tmp_path / "payload"
    excluded: list[str] = []
    captured = capture._copy_component(
        active,
        payload,
        Path(".local/share/icons/Tela-manjaro-dark"),
        home,
        excluded,
        "icon-theme",
    )

    root = payload / ".local/share/icons/Tela-manjaro-dark"
    assert (root / "index.theme").is_file()
    assert (root / "folder.svg").read_text(encoding="utf-8") == "<svg>base</svg>"
    assert not (root / "folder.svg").is_symlink()
    assert (root / "scalable/base.svg").is_file()
    assert not (root / "scalable").is_symlink()
    assert not (root / "escape.svg").exists()
    assert any("escapes trusted roots" in item for item in excluded)
    assert captured


def test_v063_sddm_theme_can_dereference_sibling_theme_assets_only(tmp_path: Path):
    themes = tmp_path / "usr/share/sddm/themes"
    base = themes / "Base"
    theme = themes / "Fancy"
    base.mkdir(parents=True)
    theme.mkdir(parents=True)
    (theme / "Main.qml").write_text("// qml", encoding="utf-8")
    (base / "background.jpg").write_bytes(b"base-background")
    (theme / "background.jpg").symlink_to("../Base/background.jpg")
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"secret")
    (theme / "escape.jpg").symlink_to(outside)

    captured = tmp_path / "captured"
    assert capture._copy_visual_tree(theme, captured, trusted_roots=[themes])
    assert (captured / "background.jpg").read_bytes() == b"base-background"
    assert not (captured / "background.jpg").is_symlink()
    assert not (captured / "escape.jpg").exists()


def test_v063_slideshow_metadata_preserves_per_desktop_settings(tmp_path: Path):
    payload = tmp_path / "payload"
    cfg = payload / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "[Containments][7]\n"
        "wallpaperplugin=org.kde.slideshow\n"
        "[Containments][7][Wallpaper][org.kde.slideshow][General]\n"
        "Image=file://{{HOME}}/Pictures/Slides/current.jpg\n"
        "SlidePaths=file://{{HOME}}/Pictures/Slides\n"
        "SlideTimer=300\n"
        "Randomize=true\n",
        encoding="utf-8",
    )

    state = capture._captured_slideshow_state(
        payload, [{"id": 7, "screen": 2, "plugin": "org.kde.slideshow"}]
    )

    assert state["active"] is True
    assert state["containments"] == 1
    assert state["paths"] == ["{{HOME}}/Pictures/Slides"]
    entry = state["entries"][0]
    assert entry["screen"] == 2
    assert entry["settings"]["SlideTimer"] == "300"
    assert entry["settings"]["Randomize"] == "true"
    assert entry["settings"]["SlidePaths"] == "file://{{HOME}}/Pictures/Slides"


def test_v063_first_login_converges_icons_colors_plasma_and_slideshow_without_global_theme_reset():
    script = native.NATIVE_FIRST_LOGIN
    assert "plasma-changeicons" in script
    assert "plasma-apply-colorscheme" in script
    assert "plasma-apply-desktoptheme" in script
    assert "plasma-apply-lookandfeel" not in script
    assert "org.kde.PlasmaShell.evaluateScript" in script
    assert "org.kde.slideshow" in script
    assert "SlidePaths" in script
    assert "time.sleep(2)" in script


def test_v063_sddm_sync_matches_kde_style_and_runs_again_before_first_display_manager():
    script = native.NATIVE_SYSTEM_VISUAL
    service = native.NATIVE_PRELOGIN_SERVICE
    assert 'pwd.getpwnam("sddm")' in script
    assert 'Path(".config/kdeglobals")' in script
    assert 'Path(".config/plasmarc")' in script
    assert 'Path(".config/kcminputrc")' in script
    assert "promote_sddm_desktop_assets" in script
    assert '"/usr/share/icons"' in script
    assert '"/usr/share/plasma/desktoptheme"' in script
    assert '"--boot" in sys.argv[1:]' in script
    assert 'Path("/run/linux-iso") if _live_boot() else Path("/var/lib/linux-iso")' in script
    assert "ExecStart=/usr/lib/linux-iso/native-system-visual.py --boot" in service
    assert service.index("native-system-visual.py --boot") < service.index("native-prelogin.py")


def test_v063_stage_rejects_schema_11_and_requires_fresh_appearance_capture(tmp_path: Path, monkeypatch):
    profile = tmp_path / "profile"
    (profile / "payload/home").mkdir(parents=True)
    (profile / "manifest.yaml").write_text(yaml.safe_dump(_manifest(11), sort_keys=False), encoding="utf-8")
    base = tmp_path / "base.iso"
    base.write_bytes(b"iso")
    monkeypatch.setattr(native, "verify_profile", lambda _path: SimpleNamespace(ok=True))
    monkeypatch.setattr(native, "probe_native_iso", lambda _path: _probe(base))

    try:
        native.stage_native_project(profile, base, tmp_path / "build")
    except native.NativeIsoError as exc:
        assert "appearance/SDDM/slideshow fidelity schema" in str(exc)
    else:
        raise AssertionError("schema 11 must require a one-time v12 recapture")


def test_v063_stage_embeds_runtime_appearance_and_slideshow_state(tmp_path: Path, monkeypatch):
    profile = tmp_path / "profile"
    (profile / "payload/home").mkdir(parents=True)
    manifest = _manifest(12)
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    base = tmp_path / "base.iso"
    base.write_bytes(b"iso")
    monkeypatch.setattr(native, "verify_profile", lambda _path: SimpleNamespace(ok=True))
    monkeypatch.setattr(native, "probe_native_iso", lambda _path: _probe(base))

    out = native.stage_native_project(profile, base, tmp_path / "build", result=tmp_path / "result")
    native_json = json.loads((out / "native.json").read_text(encoding="utf-8"))
    restore = json.loads((out / "profile/native-restore.json").read_text(encoding="utf-8"))

    assert native_json["appearance"]["icon-theme"] == "Tela-manjaro-dark"
    assert native_json["appearance"]["color-scheme"] == "Nordic"
    assert native_json["appearance"]["plasma-theme"] == "Nordic"
    assert native_json["visual_fidelity"]["slideshow"]["entries"][0]["settings"]["SlideTimer"] == "300"
    assert restore["schema"] == 3
    assert restore["appearance"] == native_json["appearance"]
    assert restore["slideshow"]["active"] is True


def test_v063_verification_rejects_truncated_active_icon_theme_bundle(tmp_path: Path):
    profile = tmp_path / "profile"
    icon_root = profile / "payload/home/.local/share/icons/Tela-manjaro-dark"
    icon_root.mkdir(parents=True)
    (icon_root / "only.svg").write_text("<svg/>", encoding="utf-8")
    slides = profile / "payload/home/Pictures/Slides"
    slides.mkdir(parents=True)
    (slides / "a.jpg").write_bytes(b"jpg")
    theme = profile / "payload/system/sddm/theme"
    theme.mkdir(parents=True)
    (theme / "Main.qml").write_text("// qml", encoding="utf-8")
    (theme / "suret-assets").mkdir()
    (theme / "suret-assets/login.jpg").write_bytes(b"jpg")
    manifest = _manifest(12)
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = verify_profile(profile)
    assert not result.ok
    assert any("lacks index.theme" in error for error in result.errors)


def test_v063_release_identity_and_retry_gate():
    assert __version__ == "0.6.5"
    retry = Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    full = Path("scripts/native-acceptance.sh").read_text(encoding="utf-8")
    assert "v0.6.5 Native retry" in retry
    assert "v0.6.5 Native ISO acceptance" in full
    assert "fidelity < 12" in retry
    assert retry.index("fidelity < 12") < retry.index('phase "Resetting previous Native build state"')
    assert "Active icon theme" in retry
    assert "desktop state(s)" in retry


def test_v063_appearance_library_includes_user_knewstuff_variants_and_skips_hicolor(tmp_path: Path):
    home = tmp_path / "home"
    icons = home / ".local/share/icons"
    for name in ("Nordic-bluish", "Nordic-darker", "Nordic-green", "Tela-manjaro", "Tela-manjaro-dark", "Tela-manjaro-light", "hicolor"):
        root = icons / name
        root.mkdir(parents=True)
        (root / "index.theme").write_text(f"[Icon Theme]\nName={name}\n", encoding="utf-8")

    entries = capture._appearance_library_entries(home)
    targets = {target.as_posix() for kind, _src, target in entries if kind == "icon-theme"}

    assert ".local/share/icons/Nordic-bluish" in targets
    assert ".local/share/icons/Nordic-darker" in targets
    assert ".local/share/icons/Nordic-green" in targets
    assert ".local/share/icons/Tela-manjaro" in targets
    assert ".local/share/icons/Tela-manjaro-dark" in targets
    assert ".local/share/icons/Tela-manjaro-light" in targets
    assert ".local/share/icons/hicolor" not in targets


def test_v063_generated_first_login_builds_slideshow_dbus_script_with_portable_home(monkeypatch, tmp_path: Path):
    namespace: dict[str, object] = {"__name__": "suret_first_login_test"}
    exec(native.NATIVE_FIRST_LOGIN, namespace)
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_which(name: str):
        return "/usr/bin/qdbus6" if name == "qdbus6" else None

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return Result()

    namespace["shutil"].which = fake_which
    namespace["subprocess"].run = fake_run
    data = {
        "slideshow": {
            "active": True,
            "entries": [
                {
                    "screen": 0,
                    "settings": {
                        "SlidePaths": "file://{{HOME}}/Pictures/Slides",
                        "SlideTimer": "240",
                        "Randomize": "true",
                    },
                }
            ],
        }
    }
    home = tmp_path / "home"
    assert namespace["apply_slideshow"](data, home) is True
    assert calls
    script = calls[0][-1]
    assert "org.kde.slideshow" in script
    assert f"file://{home}/Pictures/Slides" in script
    assert '"SlideTimer": "240"' in script
    assert "{{HOME}}" not in script


def test_v063_generated_first_login_applies_only_non_destructive_appearance_commands():
    namespace: dict[str, object] = {"__name__": "suret_first_login_appearance_test"}
    exec(native.NATIVE_FIRST_LOGIN, namespace)
    calls: list[list[str]] = []
    namespace["run"] = lambda command, timeout=30: calls.append(list(command)) or True

    namespace["apply_appearance"](
        {
            "appearance": {
                "icon-theme": "Tela-manjaro-dark",
                "color-scheme": "Nordic",
                "plasma-theme": "Nordic",
                "look-and-feel": "Nordic",
            }
        }
    )

    assert ["plasma-changeicons", "Tela-manjaro-dark"] in calls
    assert ["plasma-apply-colorscheme", "Nordic"] in calls
    assert ["plasma-apply-desktoptheme", "Nordic"] in calls
    assert not any("lookandfeel" in token.lower() for call in calls for token in call)
