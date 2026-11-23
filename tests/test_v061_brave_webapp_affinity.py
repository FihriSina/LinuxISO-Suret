from __future__ import annotations

import base64
import json
from pathlib import Path

import yaml

from linux_iso.builder import native


def _encoded(command: str) -> str:
    return base64.urlsafe_b64encode(command.encode("utf-8")).decode("ascii")


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


def test_v061_old_chatgpt_profile_is_rebound_to_brave_app_mode(tmp_path: Path):
    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    apps.mkdir(parents=True)
    launcher = apps / "chrome-chatgpt-Default.desktop"
    launcher.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=ChatGPT\n"
        "TryExec=/usr/bin/brave-browser\n"
        "Exec=xdg-open https://chatgpt.com/\n"
        f"X-Suret-Original-Exec-B64={_encoded('/usr/bin/brave-browser --profile-directory=Default --app-id=abcdefghijklmnop %U')}\n"
        "Icon=chrome-abcdefghijklmnop-Default\n"
        "StartupWMClass=crx_abcdefghijklmnop\n",
        encoding="utf-8",
    )

    result = native._rewrite_native_webapp_launchers(profile)
    text = launcher.read_text(encoding="utf-8")

    assert result["rewritten"] == 1
    assert result["vendor_apt_apps"] == ["brave-browser"]
    assert result["flatpaks"] == []
    assert "Exec=/usr/bin/brave-browser --app=https://chatgpt.com/" in text
    assert "TryExec=/usr/bin/brave-browser" in text
    assert "X-Suret-Original-Exec-B64=" not in text
    assert "StartupWMClass=crx_" not in text
    assert "--profile-directory" not in text
    assert "--app-id" not in text


def test_v061_flatpak_brave_webapp_keeps_flatpak_browser_affinity(tmp_path: Path):
    profile = tmp_path / "profile"
    apps = profile / "payload/home/Masaüstü"
    apps.mkdir(parents=True)
    launcher = apps / "ChatGPT.desktop"
    launcher.write_text(
        "[Desktop Entry]\nName=ChatGPT\n"
        "Exec=xdg-open https://chatgpt.com/\n"
        f"X-Suret-Original-Exec-B64={_encoded('flatpak run com.brave.Browser --profile-directory=Default --app-id=abc')}\n",
        encoding="utf-8",
    )

    result = native._rewrite_native_webapp_launchers(profile)
    text = launcher.read_text(encoding="utf-8")

    assert result["vendor_apt_apps"] == []
    assert result["flatpaks"] == ["com.brave.Browser"]
    assert "Exec=flatpak run com.brave.Browser --app=https://chatgpt.com/" in text
    assert "TryExec=flatpak" in text


def test_v061_webapp_rewriter_rejects_credential_url_and_arbitrary_original_command(tmp_path: Path):
    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    apps.mkdir(parents=True)
    bad_url = apps / "bad-url.desktop"
    bad_url.write_text(
        "[Desktop Entry]\nName=ChatGPT\n"
        "Exec=xdg-open https://user:pass@example.com/\n"
        f"X-Suret-Original-Exec-B64={_encoded('/usr/bin/brave-browser --app-id=abc')}\n",
        encoding="utf-8",
    )
    arbitrary = apps / "arbitrary.desktop"
    arbitrary.write_text(
        "[Desktop Entry]\nName=ChatGPT\n"
        "Exec=xdg-open https://chatgpt.com/\n"
        f"X-Suret-Original-Exec-B64={_encoded('/tmp/run-me --danger')}\n",
        encoding="utf-8",
    )

    result = native._rewrite_native_webapp_launchers(profile)
    assert result["rewritten"] == 0
    assert "Exec=xdg-open https://user:pass@example.com/" in bad_url.read_text(encoding="utf-8")
    assert "Exec=xdg-open https://chatgpt.com/" in arbitrary.read_text(encoding="utf-8")


def test_v061_brave_native_package_uses_official_vendor_apt_resolver():
    manifest = _manifest([
        {"name": "brave-browser", "provider": "apt", "installer_visible": True},
    ])
    native_apps, vendor_apps, flatpaks = native._profile_app_plan(manifest, "apt")
    assert native_apps == []
    assert vendor_apps == ["brave-browser"]
    assert flatpaks == []
    assert "brave-browser" not in native.PORTABLE_FLATPAK_FALLBACKS


def test_v061_vendor_script_contains_official_brave_repo_and_binary_key_path():
    text = native.NATIVE_INSTALL_SCRIPT
    assert "https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg" in text
    assert "https://brave-browser-apt-release.s3.brave.com/brave-browser.sources" in text
    assert "https://brave-browser-apt-release.s3.brave.com stable main" in text
    assert 'brave-browser) vendor_name="Brave Browser"; vendor_pkg="brave-browser"' in text
    assert 'key_format="raw"' in text
    assert 'gpg --batch --show-keys "$key_tmp"' in text


def test_v061_stage_existing_profile_rewrites_chatgpt_without_recapture(tmp_path: Path, monkeypatch):
    from linux_iso.assets import sha256_file

    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    apps.mkdir(parents=True)
    launcher = apps / "ChatGPT.desktop"
    launcher.write_text(
        "[Desktop Entry]\nName=ChatGPT\n"
        "Exec=xdg-open https://chatgpt.com/\n"
        f"X-Suret-Original-Exec-B64={_encoded('/usr/bin/brave-browser --profile-directory=Default --app-id=abc')}\n",
        encoding="utf-8",
    )
    manifest = _manifest([
        {"name": "git", "provider": "apt", "installer_visible": True},
        {"name": "brave-browser", "provider": "apt", "installer_visible": True},
    ])
    # Verification only requires manifest consistency in production; this unit
    # test stubs verification while keeping a real payload launcher.
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    monkeypatch.setattr(native, "verify_profile", lambda _p: type("R", (), {"ok": True})())
    monkeypatch.setattr(native, "probe_native_iso", lambda _p: _probe())
    base = tmp_path / "Pardus-25.2-XFCE-amd64.iso"
    base.write_bytes(b"fake")
    out = tmp_path / "out"
    native.stage_native_project(profile, base, out, result=tmp_path / "result")

    meta = json.loads((out / "native.json").read_text(encoding="utf-8"))
    rendered = (out / "profile/payload/home/.local/share/applications/ChatGPT.desktop").read_text(encoding="utf-8")
    assert "brave-browser" in meta["vendor_apt_apps"]
    assert meta["webapp_bindings"]["rewritten"] == 1
    assert "Exec=/usr/bin/brave-browser --app=https://chatgpt.com/" in rendered
    assert "xdg-open https://chatgpt.com/" not in rendered
    assert "--profile-directory" not in rendered
