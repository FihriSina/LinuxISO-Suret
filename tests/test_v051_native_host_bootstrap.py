from pathlib import Path


def test_v051_native_acceptance_bootstraps_before_probe():
    script = Path("scripts/native-acceptance.sh").read_text(encoding="utf-8")
    bootstrap = script.index('"$HERE/scripts/bootstrap-native-host.sh"')
    sync = script.index("uv sync")
    probe = script.index('uv run linux-iso probe-iso "$BASE_ISO"')
    assert bootstrap < sync < probe
    assert "Native ISO acceptance" in script


def test_v051_bootstrap_covers_full_native_toolchain():
    script = Path("scripts/bootstrap-native-host.sh").read_text(encoding="utf-8")
    for command in (
        "xorriso",
        "unsquashfs",
        "mksquashfs",
        "rsync",
        "chroot",
        "mount",
        "umount",
        "qemu-system-x86_64",
        "qemu-img",
    ):
        assert f"[{command}]" in script
    for package in ("xorriso", "squashfs-tools", "qemu-system-x86", "qemu-utils", "ovmf"):
        assert package in script
    assert "apt-get install -y --no-install-recommends" in script
    assert "apt-get update" in script


def test_v051_bootstrap_verifies_after_install():
    script = Path("scripts/bootstrap-native-host.sh").read_text(encoding="utf-8")
    assert "Native dependency bootstrap incomplete" in script
    assert "Native host dependencies: installed and verified" in script
    assert "Automatic dependency bootstrap currently supports apt-based hosts only" in script


def test_v051_retry_native_reuses_profile_and_bootstraps():
    script = Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    assert 'bootstrap-native-host.sh' in script
    assert 'uv run linux-iso verify "$PROFILE"' in script
    assert 'uv run linux-iso scan' not in script
    assert 'reset_native_dir "$BUILD" build' in script
    assert 'reset_native_dir "$RESULT" result' in script
    assert 'guard_reset_dir "$target"' in script
    assert 'uv run linux-iso stage-native "$PROFILE" "$BASE_ISO"' in script
