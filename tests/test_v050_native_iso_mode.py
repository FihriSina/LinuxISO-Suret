from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.builder.native import _profile_app_plan, probe_iso_tree
from linux_iso.cli import build_parser


def test_v050_probe_pardus25_tree(tmp_path: Path):
    tree = tmp_path / "iso"
    (tree / ".disk").mkdir(parents=True)
    (tree / ".disk/info").write_text("Pardus 25.2 XFCE amd64\n", encoding="utf-8")
    (tree / "live").mkdir()
    for name in ("filesystem.squashfs", "vmlinuz", "initrd.img"):
        (tree / "live" / name).write_bytes(b"x")
    probe = probe_iso_tree(tree)
    assert probe.distro_id == "pardus"
    assert probe.distro_version == "25.2"
    assert probe.package_family == "apt"
    assert probe.live_rootfs == "/live/filesystem.squashfs"
    assert probe.installer == "pardus-installer"
    assert probe.desktop_hint == "xfce"
    assert probe.supports_native_build


def test_v050_profile_app_plan_keeps_same_family_and_flatpak():
    manifest = {
        "packages": [
            {"name": "git", "provider": "apt", "installer_visible": True},
            {"name": "base-files", "provider": "apt", "installer_visible": False},
            {"name": "org.mozilla.firefox", "provider": "flatpak", "installer_visible": True},
            {"name": "foo", "provider": "dnf", "installer_visible": True},
            {"name": "breeze", "provider": "apt", "installer_visible": True, "required_for_appearance": True},
        ]
    }
    native, flatpaks = _profile_app_plan(manifest, "apt")
    assert native == ["git"]
    assert flatpaks == ["org.mozilla.firefox"]


def test_v050_cli_exposes_native_commands():
    parser = build_parser()
    args = parser.parse_args(["probe-iso", "/tmp/base.iso"])
    assert args.command == "probe-iso"
    args = parser.parse_args(["stage-native", "/tmp/profile", "/tmp/base.iso"])
    assert args.command == "stage-native"
    args = parser.parse_args(["build-native", "/tmp/profile", "/tmp/base.iso"])
    assert args.command == "build-native"


def test_v050_release_version():
    data = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.5.1"' in data


def test_v050_stage_native_generates_pardus_remaster_scripts(tmp_path: Path, monkeypatch):
    from linux_iso.assets import sha256_file
    from linux_iso.builder import native

    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    cfg = payload / "kdeglobals"
    cfg.write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "distro_name": "Pardus GNU/Linux 25", "architecture": "x86_64"},
        "desktop": {
            "desktop": "kde-plasma",
            "configs": [{"source": "{{HOME}}/.config/kdeglobals", "destination": "{{HOME}}/.config/kdeglobals", "kind": "config", "sha256": sha256_file(cfg)}],
            "custom_assets": [], "widgets": [], "user_plasmoids": [], "widget_details": [], "component_details": [],
        },
        "packages": [
            {"name": "git", "provider": "apt", "category": "development", "required_for_appearance": False, "installer_visible": True},
            {"name": "com.google.AndroidStudio", "provider": "flatpak", "category": "development", "required_for_appearance": False, "installer_visible": True},
        ],
        "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    monkeypatch.setattr(native, "probe_native_iso", lambda _p: native.NativeIsoProbe(
        base_iso="/tmp/Pardus.iso", distro_id="pardus", distro_name="Pardus 25.2 XFCE",
        distro_version="25.2", architecture="x86_64", package_family="apt",
        live_rootfs="/live/filesystem.squashfs", kernel="/live/vmlinuz", initrd="/live/initrd.img",
        installer="pardus-installer", desktop_hint="xfce", supports_native_build=True,
    ))
    monkeypatch.setattr(native, "verify_profile", lambda _p: type("R", (), {"ok": True})())

    base = tmp_path / "Pardus-25.2-XFCE-amd64.iso"
    base.write_bytes(b"fake")
    out = tmp_path / "native-build"
    native.stage_native_project(profile, base, out, result=tmp_path / "result")

    build = (out / "build-native.sh").read_text(encoding="utf-8")
    install = (out / "native-install.sh").read_text(encoding="utf-8")
    first = (out / "native-first-login.py").read_text(encoding="utf-8")
    meta = (out / "native.json").read_text(encoding="utf-8")

    assert "xorriso -osirrox on" in build
    assert "live/filesystem.squashfs" in build
    assert "-boot_image any replay" in build
    assert "kde-plasma-desktop" in install
    assert "pardus-installer" in meta
    assert "git" in install
    assert "com.google.AndroidStudio" in install
    assert "payload/home" in first
    assert (out / "profile/native-restore.json").is_file()
    assert "Before=display-manager.service" in (out / "linux-iso-native-prelogin.service").read_text(encoding="utf-8")
    assert "AccountsService" in (out / "native-prelogin.py").read_text(encoding="utf-8")
    assert "GRUB_THEME" in (out / "native-system-visual.py").read_text(encoding="utf-8")
    assert "suret-source" in (out / "native-system-visual.py").read_text(encoding="utf-8")


def test_v050_native_mode_refuses_cross_distro_profile(tmp_path: Path, monkeypatch):
    from linux_iso.builder import native

    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "manifest.yaml").write_text(yaml.safe_dump({
        "source": {"distro_id": "ubuntu"},
        "desktop": {"desktop": "kde-plasma"},
        "packages": [],
    }), encoding="utf-8")
    monkeypatch.setattr(native, "verify_profile", lambda _p: type("R", (), {"ok": True})())
    monkeypatch.setattr(native, "probe_native_iso", lambda _p: native.NativeIsoProbe(
        base_iso="/tmp/p.iso", distro_id="pardus", distro_name="Pardus", distro_version="25.2",
        architecture="x86_64", package_family="apt", live_rootfs="/live/filesystem.squashfs",
        kernel=None, initrd=None, installer="pardus-installer", supports_native_build=True,
    ))
    base = tmp_path / "base.iso"; base.write_bytes(b"fake")
    try:
        native.stage_native_project(profile, base, tmp_path / "out")
    except native.NativeIsoError as exc:
        assert "refuses silent cross-distro grafting" in str(exc)
    else:
        raise AssertionError("cross-distro native build should have been rejected")


def test_v050_capture_launcher_translation_is_reversible():
    from linux_iso.capture import _rewrite_desktop_exec_compat
    import base64

    source = "[Desktop Entry]\nName=Pardus Hakkında\nExec=pardus-about\nIcon=pardus\n"
    captured = _rewrite_desktop_exec_compat(source)
    assert "Exec=kinfocenter" in captured
    marker = next(line.split("=", 1)[1] for line in captured.splitlines() if line.startswith("X-Suret-Original-Exec-B64="))
    assert base64.urlsafe_b64decode(marker.encode("ascii")).decode("utf-8") == "pardus-about"


def test_v050_native_stage_restores_distro_launcher_but_keeps_portable_fallback(tmp_path: Path):
    import base64
    from linux_iso.builder.native import _restore_native_launcher_execs

    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    apps.mkdir(parents=True)
    original = base64.urlsafe_b64encode(b"pardus-about").decode("ascii")
    (apps / "pardus-about.desktop").write_text(
        "[Desktop Entry]\nName=Pardus Hakkında\nExec=kinfocenter\n"
        f"X-Suret-Original-Exec-B64={original}\n",
        encoding="utf-8",
    )
    code_original = base64.urlsafe_b64encode(b"/usr/share/code/code --unity-launch %F").decode("ascii")
    (apps / "code.desktop").write_text(
        "[Desktop Entry]\nName=Visual Studio Code\nExec=flatpak run com.visualstudio.code\n"
        f"X-Suret-Original-Exec-B64={code_original}\n",
        encoding="utf-8",
    )

    assert _restore_native_launcher_execs(profile) == 1
    pardus = (apps / "pardus-about.desktop").read_text(encoding="utf-8")
    code = (apps / "code.desktop").read_text(encoding="utf-8")
    assert "Exec=pardus-about" in pardus
    assert "X-Suret-Original" not in pardus
    assert "Exec=flatpak run com.visualstudio.code" in code
    assert "X-Suret-Original" not in code


def test_v050_native_app_plan_resolves_vendor_apt_packages_to_flatpak():
    manifest = {
        "packages": [
            {"name": "code", "provider": "apt", "installer_visible": True},
            {"name": "signal-desktop", "provider": "apt", "installer_visible": True},
            {"name": "git", "provider": "apt", "installer_visible": True},
        ]
    }
    native, flatpaks = _profile_app_plan(manifest, "apt")
    assert native == ["git"]
    assert flatpaks == ["com.visualstudio.code", "org.signal.Signal"]
