from __future__ import annotations

import subprocess
from pathlib import Path

from linux_iso import __version__
from linux_iso.builder import native


def test_v053_version_bumped():
    assert __version__ == "0.6.0"


def test_v053_iso_probe_uses_xorriso_find_echo_not_shell_print(monkeypatch, tmp_path: Path):
    seen: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: int = 120):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="'/live/filesystem.squashfs'\n", stderr="")

    monkeypatch.setattr(native, "_require_tools", lambda _names: None)
    monkeypatch.setattr(native, "_run", fake_run)
    files = native._list_iso(tmp_path / "base.iso")

    assert "/live/filesystem.squashfs" in files
    assert seen
    cmd = seen[0]
    assert "-print" not in cmd
    assert cmd[-3:] == ["-exec", "echo", "--"]
    assert "-exec" in cmd


def test_v053_generated_build_uses_xorriso_156_compatible_find():
    text = native.NATIVE_BUILD_SCRIPT
    assert '-find "/$ROOTFS_REL" -type f -exec echo --' in text
    assert '-find "/$ROOTFS_REL" -type f -print' not in text


def test_v053_repack_does_not_replace_whole_iso_tree_before_boot_replay():
    text = native.NATIVE_BUILD_SCRIPT
    assert '-map "$ISO_ROOT" / -boot_image any replay' not in text
    assert '-map "$ISO_ROOT/$ROOTFS_REL" "/$ROOTFS_REL"' in text
    assert '-map "$ISO_ROOT/$LIVE_DIR/filesystem.size" "/$LIVE_DIR/filesystem.size"' in text
    assert 'XORRISO_ARGS+=( -boot_image any replay -commit )' in text


def test_v053_sbin_path_is_normalized_across_host_and_generated_build_scripts():
    expected = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}'
    for rel in (
        "scripts/bootstrap-native-host.sh",
        "scripts/native-acceptance.sh",
        "scripts/retry-native-acceptance.sh",
    ):
        assert expected in Path(rel).read_text(encoding="utf-8")
    assert expected in native.NATIVE_BUILD_SCRIPT


def test_v053_bootstrap_sees_chroot_when_only_sbin_contains_it(tmp_path: Path):
    # Static guarantee: PATH normalization happens before dependency probing.
    text = Path("scripts/bootstrap-native-host.sh").read_text(encoding="utf-8")
    export_at = text.index('export PATH=')
    probe_at = text.index('declare -A CMD_PKG')
    assert export_at < probe_at
    assert '[chroot]=coreutils' in text
