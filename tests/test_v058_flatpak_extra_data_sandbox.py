from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from linux_iso import __version__
from linux_iso.builder import native


def _extract_function(script: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n(?P<body>.*?\n)\}}\n", script, flags=re.MULTILINE | re.DOTALL)
    assert match, f"missing shell function: {name}"
    return f"{name}() {{\n{match.group('body')}}}\n"


def test_v058_version_and_acceptance_banners_are_bumped():
    assert __version__ == "0.6.0"
    assert "v0.6.0 Native retry" in Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    assert "v0.6.0 Native ISO acceptance" in Path("scripts/native-acceptance.sh").read_text(encoding="utf-8")


def test_v058_chroot_root_is_a_real_slave_bind_mount_for_bubblewrap():
    text = native.NATIVE_BUILD_SCRIPT
    bind = text.index('sudo mount --bind "$ROOTFS" "$ROOTFS"')
    suid = text.index('sudo mount -o remount,bind,suid "$ROOTFS"')
    slave = text.index('sudo mount --make-rslave "$ROOTFS"')
    dev = text.index('sudo mount --rbind /dev "$ROOTFS/dev"')
    assert bind < suid < slave < dev
    cleanup = text.split("cleanup_mounts() (", 1)[1].split(")\n", 1)[0]
    assert 'sudo umount -l "$ROOTFS"' in cleanup
    for rel in ("scripts/retry-native-acceptance.sh", "scripts/native-acceptance.sh"):
        acceptance = Path(rel).read_text(encoding="utf-8")
        assert 'sudo umount -l "$rootfs"' in acceptance


def test_v058_flatpak_build_is_locale_and_gpu_independent():
    text = native.NATIVE_INSTALL_SCRIPT
    assert "export LANG=C.UTF-8" in text
    assert "export LC_ALL=C.UTF-8" in text
    assert "export FLATPAK_GL_DRIVERS=default" in text
    assert "export FLATPAK_TTY_PROGRESS=0" in text
    assert "export FLATPAK_FANCY_OUTPUT=0" in text
    assert "host-specific GPU Flatpak runtime leaked" in text
    assert "VAAPI\\.nvidia" in text
    assert "amd\\.amf" in text


def test_v058_flatpak_uses_temporary_bwrap_setuid_and_restores_mode(tmp_path: Path):
    text = native.NATIVE_INSTALL_SCRIPT
    restore = _extract_function(text, "restore_build_bwrap")
    helper = tmp_path / "bwrap"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o755)
    shell = "\n".join(
        [
            "set -euo pipefail",
            f"BWRAP_BUILD_PATH={str(helper)!r}",
            'BWRAP_BUILD_MODE="755"',
            restore,
            'chmod u+s "$BWRAP_BUILD_PATH"',
            '[[ -u "$BWRAP_BUILD_PATH" ]]',
            "restore_build_bwrap",
            '[[ ! -u "$BWRAP_BUILD_PATH" ]]',
            '[[ "$(stat -Lc %a "$BWRAP_BUILD_PATH")" == 755 ]]',
        ]
    )
    proc = subprocess.run(["bash", "-c", shell], text=True, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert 'export FLATPAK_BWRAP="$BWRAP_BUILD_PATH"' in text
    assert 'chmod u+s "$BWRAP_BUILD_PATH"' in text
    assert "temporary setuid bubblewrap mode was not removed" in text


def test_v058_work_tree_is_sealed_during_setuid_flatpak_window():
    text = native.NATIVE_BUILD_SCRIPT
    seal = text.index("seal_work_tree\nset +e")
    chroot = text.index('sudo chroot "$ROOTFS" /usr/bin/env REPLACE_DESKTOP=')
    sanitize = text.index("sanitize_build_privileges\nunseal_work_tree", chroot)
    assert seal < chroot < sanitize
    assert 'sudo chown root:root "$WORK"' in text
    assert 'sudo chmod 0700 "$WORK"' in text
    assert 'sudo chmod u-s "$bwrap_path"' in text
    assert 'sudo chown "$WORK_ORIG_UID:$WORK_ORIG_GID" "$WORK"' in text



def test_v058_chroot_masks_build_host_kernel_module_state():
    text = native.NATIVE_BUILD_SCRIPT
    assert 'linux-iso-hw-mask/proc-modules' in text
    assert 'mount --bind "$ROOTFS/run/linux-iso-hw-mask/proc-modules" "$ROOTFS/proc/modules"' in text
    assert 'mount --bind "$ROOTFS/run/linux-iso-hw-mask/sys-module" "$ROOTFS/sys/module"' in text
    assert 'mount -t tmpfs -o mode=0755,nosuid,nodev tmpfs "$ROOTFS/run"' in text

def test_v058_failed_chroot_is_sanitized_before_exit():
    text = native.NATIVE_BUILD_SCRIPT
    fragment = text.split('seal_work_tree\nset +e', 1)[1].split('# Never allow the build-only fallback', 1)[0]
    assert "CHROOT_INSTALL_RC=$?" in fragment
    assert "set -e" in fragment
    assert "sanitize_build_privileges" in fragment
    assert "unseal_work_tree" in fragment
    assert 'if (( CHROOT_INSTALL_RC != 0 )); then' in fragment
    assert 'exit "$CHROOT_INSTALL_RC"' in fragment
