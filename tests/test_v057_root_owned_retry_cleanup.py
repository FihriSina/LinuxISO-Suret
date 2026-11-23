from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

from linux_iso import __version__
from linux_iso.builder import native


def _extract_function(text: str, name: str) -> str:
    start = text.index(f"{name}() {{")
    pos = start
    depth = 0
    seen = False
    while pos < len(text):
        ch = text[pos]
        if ch == "{":
            depth += 1
            seen = True
        elif ch == "}":
            depth -= 1
            if seen and depth == 0:
                end = text.find("\n", pos)
                return text[start : (len(text) if end == -1 else end + 1)]
        pos += 1
    raise AssertionError(f"unterminated shell function: {name}")


def _minimal_profile(path: Path) -> Path:
    (path / "payload/home").mkdir(parents=True)
    manifest = {
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
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home", "asset_mode": "active"},
    }
    (path / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return path


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


def test_v057_version_and_retry_banner_are_bumped():
    assert __version__ == "0.6.0"
    assert "v0.6.0 Native retry" in Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    assert "v0.6.0 Native ISO acceptance" in Path("scripts/native-acceptance.sh").read_text(encoding="utf-8")


def test_v057_acceptance_reset_detaches_mounts_before_privileged_build_removal():
    for rel in ("scripts/retry-native-acceptance.sh", "scripts/native-acceptance.sh"):
        text = Path(rel).read_text(encoding="utf-8")
        assert "cleanup_stale_native_mounts()" in text
        assert 'for path in run sys proc dev; do' in text
        assert 'sudo umount -R -l "$rootfs/$path"' in text
        assert 'sudo rm -rf --one-file-system -- "$target"' in text
        assert 'rm -rf -- "$BUILD" "$RESULT"' not in text
        assert 'reset_native_dir "$BUILD" build' in text
        assert 'reset_native_dir "$RESULT" result' in text


def test_v057_default_root_owned_build_falls_back_to_safe_sudo_cleanup(tmp_path: Path):
    text = Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    funcs = "\n".join(
        _extract_function(text, name)
        for name in (
            "guard_reset_dir",
            "cleanup_stale_native_mounts",
            "trusted_native_project_marker",
            "reset_native_dir",
        )
    )
    home = tmp_path / "home"
    build = home / "linux-iso-native-build"
    (build / "work/rootfs/etc").mkdir(parents=True)
    (build / "work/rootfs/etc/root-owned-simulated").write_text("x", encoding="utf-8")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    log = tmp_path / "sudo.log"
    (fakebin / "rm").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (fakebin / "sudo").write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {str(log)!r}\n"
        "cmd=$1; shift\n"
        "case \"$cmd\" in\n"
        "  umount) exit 0 ;;\n"
        "  rm) exec /bin/rm \"$@\" ;;\n"
        "  *) exec \"$cmd\" \"$@\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (fakebin / "rm").chmod(0o755)
    (fakebin / "sudo").chmod(0o755)

    shell = "\n".join(
        [
            "set -euo pipefail",
            f"HOME={str(home)!r}",
            'DEFAULT_BUILD="$HOME/linux-iso-native-build"',
            'DEFAULT_RESULT="$HOME/linux-iso-native-result"',
            funcs,
            'reset_native_dir "$DEFAULT_BUILD" build',
        ]
    )
    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:/usr/bin:/bin"
    proc = subprocess.run(["bash", "-c", shell], text=True, capture_output=True, env=env, check=False)
    assert proc.returncode == 0, proc.stderr
    assert not build.exists()
    calls = log.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("umount -R -l") and line.endswith("/work/rootfs/dev") for line in calls)
    rm_index = next(i for i, line in enumerate(calls) if line.startswith("rm -rf --one-file-system --"))
    # v0.6.0 additionally detaches the ROOTFS self-bind after recursively
    # detaching child pseudo-filesystems; both must happen before deletion.
    assert all(("umount -R -l" in line) or line.startswith("umount -l ") for line in calls[:rm_index])
    assert any(line == f"umount -l {build / 'work/rootfs'}" for line in calls[:rm_index])


def test_v057_custom_build_requires_owned_suret_marker_before_sudo_fallback():
    text = Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    assert 'trusted_native_project_marker "$target" && trusted_before=1 || true' in text
    assert '"linux-iso-suret-native-project-v1"' in text
    assert "stat -Lc '%u'" in text
    assert '"$target" != "$DEFAULT_BUILD" && "$trusted_before" != "1"' in text


def test_v057_stage_writes_cleanup_trust_marker_and_build_uses_mount_safe_work_reset(tmp_path: Path, monkeypatch):
    profile = _minimal_profile(tmp_path / "profile")
    base = tmp_path / "Pardus-25.2-XFCE-amd64.iso"
    base.write_bytes(b"fake")
    out = tmp_path / "custom-native-build"
    monkeypatch.setattr(native, "probe_native_iso", lambda _p: _probe())
    native.stage_native_project(profile, base, out, result=tmp_path / "result")

    marker = out / ".suret-native-project"
    assert marker.read_text(encoding="utf-8") == "linux-iso-suret-native-project-v1\n"
    build = (out / "build-native.sh").read_text(encoding="utf-8")
    reset_slice = build.split("trap on_exit EXIT", 1)[1].split('echo "[1/8]', 1)[0]
    assert "cleanup_mounts" in reset_slice
    assert 'sudo rm -rf --one-file-system -- "$WORK"' in reset_slice
    assert 'sudo rm -rf -- "$WORK"' not in build


def test_v057_stale_mount_cleanup_never_privileged_umounts_symlinked_pseudofs(tmp_path: Path):
    text = Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    func = _extract_function(text, "cleanup_stale_native_mounts")
    build = tmp_path / "build"
    rootfs = build / "work/rootfs"
    rootfs.mkdir(parents=True)
    (rootfs / "run").symlink_to("/run")
    (rootfs / "dev").mkdir()
    fakebin = tmp_path / "fakebin2"
    fakebin.mkdir()
    log = tmp_path / "sudo2.log"
    (fakebin / "sudo").write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {str(log)!r}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (fakebin / "sudo").chmod(0o755)
    shell = "\n".join(["set -euo pipefail", func, f"cleanup_stale_native_mounts {str(build)!r}"])
    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:/usr/bin:/bin"
    proc = subprocess.run(["bash", "-c", shell], text=True, capture_output=True, env=env, check=False)
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert not any(str(rootfs / "run") in line for line in calls)
    assert any(str(rootfs / "dev") in line for line in calls)
