from __future__ import annotations

import base64
import json
from pathlib import Path

import yaml

from linux_iso import __version__
from linux_iso.builder import native


def _manifest(packages: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "source": {
            "distro_id": "pardus",
            "distro_name": "Pardus GNU/Linux 25",
            "distro_version": "25.2",
            "architecture": "x86_64",
        },
        "desktop": {
            "desktop": "kde-plasma",
            "configs": [],
            "custom_assets": [],
            "widgets": [],
            "user_plasmoids": [],
            "widget_details": [],
            "component_details": [],
        },
        "packages": packages,
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "asset_mode": "active",
            "fidelity_schema": 10,
        },
    }


def _probe() -> native.NativeIsoProbe:
    return native.NativeIsoProbe(
        base_iso="/tmp/Pardus-25.2-XFCE-amd64.iso",
        distro_id="pardus",
        distro_name="Pardus 25.2 XFCE",
        distro_version="25.2",
        architecture="x86_64",
        package_family="apt",
        live_rootfs="/live/filesystem.squashfs",
        kernel="/live/vmlinuz",
        initrd="/live/initrd.img",
        installer="pardus-installer",
        desktop_hint="xfce",
        supports_native_build=True,
    )


def test_v059_version_and_acceptance_banners_are_bumped():
    assert __version__ == "0.6.3"
    retry = Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    full = Path("scripts/native-acceptance.sh").read_text(encoding="utf-8")
    assert "v0.6.3 Native retry" in retry
    assert "v0.6.3 Native ISO acceptance" in full
    for text in (retry, full):
        assert 'phase "Native application plan"' in text
        assert '("Vendor APT", "vendor_apt_apps")' in text
        assert '("Flatpak", "flatpaks")' in text


def test_v059_apt_code_signal_use_vetted_vendor_resolvers_but_true_flatpaks_stay_flatpak():
    manifest = _manifest(
        [
            {"name": "code", "provider": "apt", "installer_visible": True},
            {"name": "signal-desktop", "provider": "apt", "installer_visible": True},
            {"name": "git", "provider": "apt", "installer_visible": True},
            {"name": "org.signal.Signal", "provider": "flatpak", "installer_visible": True},
            {"name": "steam", "provider": "apt", "installer_visible": True},
        ]
    )
    native_apps, vendor_apps, flatpaks = native._profile_app_plan(manifest, "apt")
    assert native_apps == ["git"]
    assert vendor_apps == ["microsoft-vscode", "signal-desktop"]
    assert flatpaks == ["org.signal.Signal", "com.valvesoftware.Steam"]


def test_v059_vendor_native_resolution_restores_only_matching_flatpak_rewritten_launcher(tmp_path: Path):
    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    apps.mkdir(parents=True)

    code_original = base64.urlsafe_b64encode(b"/usr/share/code/code --unity-launch %F").decode("ascii")
    steam_original = base64.urlsafe_b64encode(b"steam %U").decode("ascii")
    (apps / "code.desktop").write_text(
        "[Desktop Entry]\nExec=flatpak run com.visualstudio.code\n"
        f"X-Suret-Original-Exec-B64={code_original}\n",
        encoding="utf-8",
    )
    (apps / "steam.desktop").write_text(
        "[Desktop Entry]\nExec=flatpak run com.valvesoftware.Steam\n"
        f"X-Suret-Original-Exec-B64={steam_original}\n",
        encoding="utf-8",
    )

    restored = native._restore_native_launcher_execs(
        profile, restore_portable_execs={"flatpak run com.visualstudio.code"}
    )
    assert restored == 1
    assert "Exec=/usr/share/code/code --unity-launch %F" in (apps / "code.desktop").read_text(encoding="utf-8")
    assert "Exec=flatpak run com.valvesoftware.Steam" in (apps / "steam.desktop").read_text(encoding="utf-8")


def test_v059_vendor_repository_install_is_allowlisted_and_never_adds_foreign_distro_repos():
    text = native.NATIVE_INSTALL_SCRIPT
    assert "vendor_apt_apps=(__VENDOR_APT_APPS__)" in text
    assert "https://packages.microsoft.com/repos/code stable main" in text
    assert "https://updates.signal.org/desktop/apt xenial main" in text
    assert "Installing captured vendor APT applications from vetted official repositories" in text
    assert "unknown vendor APT resolver" in text
    assert "GNUPGHOME=\"$APT_RUNTIME_ROOT/vendor-gnupg\"" in text
    assert "deb http://deb.debian.org" not in text
    assert "archive.ubuntu.com" not in text
    assert "ppa.launchpad" not in text


def test_v059_flatpak_path_logs_versions_and_known_1165_regression():
    text = native.NATIVE_INSTALL_SCRIPT
    assert "Flatpak build runtime:" in text
    assert 'dpkg --compare-versions "$FLATPAK_BUILD_VERSION" eq 1.16.5' in text
    assert "known upstream /proc/self/fd sandbox regression fixed in 1.16.6" in text
    assert '"${APT_GET[@]}" install -y --no-install-recommends flatpak bubblewrap || true' in text



def test_v059_flatpak_runtime_is_installed_only_when_profile_really_contains_flatpaks():
    assert "flatpak" not in native.PARDUS_KDE_OPTIONAL_PACKAGES
    text = native.NATIVE_INSTALL_SCRIPT
    assert "flatpaks=(__FLATPAKS__)" in text
    assert "Profile contains true Flatpak applications; installing Flatpak runtime support from Pardus" in text
    assert '"${APT_GET[@]}" install -y --no-install-recommends flatpak bubblewrap' in text

def test_v059_stage_renders_vendor_plan_and_restores_native_vendor_launchers(tmp_path: Path, monkeypatch):
    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    apps.mkdir(parents=True)
    code_original = base64.urlsafe_b64encode(b"/usr/share/code/code --unity-launch %F").decode("ascii")
    (apps / "code.desktop").write_text(
        "[Desktop Entry]\nName=Visual Studio Code\nExec=flatpak run com.visualstudio.code\n"
        f"X-Suret-Original-Exec-B64={code_original}\n",
        encoding="utf-8",
    )
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(
            _manifest(
                [
                    {"name": "code", "provider": "apt", "installer_visible": True},
                    {"name": "signal-desktop", "provider": "apt", "installer_visible": True},
                ]
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(native, "probe_native_iso", lambda _p: _probe())
    monkeypatch.setattr(native, "verify_profile", lambda _p: type("R", (), {"ok": True})())
    base = tmp_path / "Pardus-25.2-XFCE-amd64.iso"
    base.write_bytes(b"fake")
    out = tmp_path / "native-build"
    native.stage_native_project(profile, base, out, result=tmp_path / "result")

    meta = json.loads((out / "native.json").read_text(encoding="utf-8"))
    install = (out / "native-install.sh").read_text(encoding="utf-8")
    launcher = (out / "profile/payload/home/.local/share/applications/code.desktop").read_text(encoding="utf-8")

    assert meta["vendor_apt_apps"] == ["microsoft-vscode", "signal-desktop"]
    assert meta["flatpaks"] == []
    assert 'vendor_apt_apps=(microsoft-vscode signal-desktop)' in install
    assert 'flatpaks=()' in install
    assert "__VENDOR_APT_APPS__" not in install
    assert "Exec=/usr/share/code/code --unity-launch %F" in launcher
    assert "flatpak run com.visualstudio.code" not in launcher
