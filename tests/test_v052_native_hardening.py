from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from linux_iso import __version__
from linux_iso.builder import native


def _minimal_profile(path: Path, *, architecture: str = "x86_64", distro_version: str = "25.2") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source": {
                    "distro_id": "pardus",
                    "distro_name": "Pardus GNU/Linux 25",
                    "distro_version": distro_version,
                    "architecture": architecture,
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
                "packages": [],
                "security": {"safe_mode": True},
                "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home", "asset_mode": "active"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _pardus_probe() -> native.NativeIsoProbe:
    return native.NativeIsoProbe(
        base_iso="/tmp/Pardus.iso",
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


def test_v052_version_sources_are_synchronized():
    assert f'version = "{__version__}"' in Path("pyproject.toml").read_text(encoding="utf-8")
    lock = Path("uv.lock").read_text(encoding="utf-8")
    assert f'name = "linux-iso"\nversion = "{__version__}"' in lock


def test_v052_native_chroot_isolated_and_metadata_refreshed():
    text = native.NATIVE_BUILD_SCRIPT
    assert 'mount -t tmpfs -o mode=0755,nosuid,nodev tmpfs "$ROOTFS/run"' in text
    assert 'mount --rbind /run' not in text
    assert 'mount --rbind /dev "$ROOTFS/dev"' in text
    assert 'filesystem.size' in text
    assert 'filesystem.packages' in text
    assert 'tolower($1) ~ /^compression:?$/' in text
    assert "! -path './isolinux/boot.cat'" in text
    assert 'Verifying remastered ISO structure' in text


def test_v052_native_install_blocks_services_and_requires_plasma():
    text = native.NATIVE_INSTALL_SCRIPT
    assert 'POLICY=/usr/sbin/policy-rc.d' in text
    assert 'exit 101' in text
    assert 'missing required KDE packages' in text
    assert 'command -v plasmashell' in text
    assert 'captured native application is unavailable in the target repositories' in text
    assert 'captured Flatpak applications exist but flatpak is not installed' in text
    assert '/usr/lib/linux-iso/native-prelogin.py || true' in text


def test_v052_live_profile_is_not_skipped_and_first_login_avoids_duplicate_copy():
    # Live detection may choose volatile runtime state, but it must never short-
    # circuit profile application as the original v0.5.2 regression did.
    assert 'marker = LIVE_TARGET_USER if live_boot() else TARGET_USER' in native.NATIVE_PRELOGIN
    assert 'if live_boot():\n        return 0' not in native.NATIVE_PRELOGIN
    assert 'marker_matches(PRELOGIN_MARKER, fingerprint)' in native.NATIVE_FIRST_LOGIN
    assert 'Recursively chowning' in native.NATIVE_PRELOGIN
    assert '*home.rglob("*")' not in native.NATIVE_PRELOGIN


def test_v052_ovmf_requires_compatible_code_vars_pair():
    bootstrap = Path("scripts/bootstrap-native-host.sh").read_text(encoding="utf-8")
    assert 'OVMF_CODE_4M.fd|/usr/share/OVMF/OVMF_VARS_4M.fd' in bootstrap
    assert 'OVMF CODE/VARS firmware pair' in bootstrap
    qemu = native.NATIVE_QEMU_SCRIPT
    assert 'OVMF_CODE_4M.fd|/usr/share/OVMF/OVMF_VARS_4M.fd' in qemu
    assert 'no compatible OVMF CODE/VARS pair found' in qemu


def test_v052_native_stage_rejects_architecture_mismatch(tmp_path: Path, monkeypatch):
    profile = _minimal_profile(tmp_path / "profile", architecture="arm64")
    base = tmp_path / "Pardus-25.2-XFCE-amd64.iso"
    base.write_bytes(b"fake")
    monkeypatch.setattr(native, "verify_profile", lambda _p: type("R", (), {"ok": True})())
    monkeypatch.setattr(native, "probe_native_iso", lambda _p: _pardus_probe())
    try:
        native.stage_native_project(profile, base, tmp_path / "out")
    except native.NativeIsoError as exc:
        assert "matching architectures" in str(exc)
    else:
        raise AssertionError("architecture mismatch should have been rejected")


def test_v052_generated_native_scripts_are_shell_syntax_safe_with_quoted_paths(tmp_path: Path, monkeypatch):
    profile = _minimal_profile(tmp_path / "profile")
    base = tmp_path / "Pardus base 'test' 25.2.iso"
    base.write_bytes(b"fake")
    result = tmp_path / "result with 'quote'"
    out = tmp_path / "native build"
    monkeypatch.setattr(native, "verify_profile", lambda _p: type("R", (), {"ok": True})())
    monkeypatch.setattr(native, "probe_native_iso", lambda _p: _pardus_probe())
    native.stage_native_project(profile, base, out, result=result)

    for name in ("build-native.sh", "native-install.sh", "test-native-qemu.sh"):
        proc = subprocess.run(["bash", "-n", str(out / name)], check=False, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
    meta = (out / "native.json").read_text(encoding="utf-8")
    assert f'"suret_version": "{__version__}"' in meta


def test_v052_native_stage_rejects_pardus_major_release_mismatch(tmp_path: Path, monkeypatch):
    profile = _minimal_profile(tmp_path / "profile", distro_version="23.4")
    base = tmp_path / "Pardus-25.2-XFCE-amd64.iso"
    base.write_bytes(b"fake")
    monkeypatch.setattr(native, "verify_profile", lambda _p: type("R", (), {"ok": True})())
    monkeypatch.setattr(native, "probe_native_iso", lambda _p: _pardus_probe())
    try:
        native.stage_native_project(profile, base, tmp_path / "out")
    except native.NativeIsoError as exc:
        assert "same major release family" in str(exc)
    else:
        raise AssertionError("Pardus major release mismatch should have been rejected")
