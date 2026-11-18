from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.builder.kiwi import generate_kiwi_project


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    (profile / "payload/home/.config").mkdir(parents=True)
    (profile / "payload/home/.config/kdeglobals").write_text(
        "[General]\nColorScheme=BreezeDark\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "architecture": "x86_64"},
        "desktop": {"desktop": "kde-plasma", "configs": [], "custom_assets": []},
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home"},
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    return profile


def test_v0320_runtime_patch_replaces_real_kubuntu_kernel_copy_instance(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    patcher = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text()
    assert 'item == "shellprocess@before_bootloader_kerncopy"' in patcher
    assert 'item = "shellprocess@linuxiso_before_bootloader_kerncopy"' in patcher
    assert 'item == "contextualprocess@before_bootloader"' in patcher
    assert "continue" in patcher


def test_v0320_runtime_patch_scrubs_stale_casper_paths(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    patcher = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text()
    assert 'Path("/etc/calamares")' in patcher
    assert 'Path("/usr/share/calamares")' in patcher
    assert '"/cdrom/casper/vmlinuz": kernel' in patcher
    assert '"/cdrom/casper/filesystem.squashfs": source' in patcher
    assert "stale Casper kernel path remains" in patcher


def test_v0320_media_helper_uses_shellprocess_fallback_and_runtime_patch(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    helper = (build / "root/usr/lib/linux-iso/prepare-calamares-media").read_text()
    assert "script:" in helper
    assert r"test -e \${ROOT}/boot/vmlinuz-\$(uname -r) || cp $KERNEL_SOURCE" in helper
    assert "patch-calamares-runtime.py \"$SOURCE\" \"$KERNEL_SOURCE\"" in helper


def test_v0320_installer_bypasses_kubuntu_launcher(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    installer = (build / "root/usr/bin/linux-iso-installer").read_text()
    assert "prepare-calamares-media" in installer
    assert "calamares-launch-normal" not in installer
    assert "exec sudo -E /usr/bin/calamares -D8" in installer
