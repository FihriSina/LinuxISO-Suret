from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso import __version__
from linux_iso.builder import native
from linux_iso.verification import verify_profile


def _manifest(*, packages: list[dict] | None = None) -> dict:
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
        "packages": packages or [],
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "asset_mode": "active",
            "fidelity_schema": 10,
        },
    }


def _profile(path: Path, *, packages: list[dict] | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "payload/home").mkdir(parents=True, exist_ok=True)
    (path / "manifest.yaml").write_text(
        yaml.safe_dump(_manifest(packages=packages), sort_keys=False), encoding="utf-8"
    )
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


def test_v054_version_and_native_scripts_are_bumped():
    assert __version__ == "0.6.0"
    assert "v0.6.0 Native ISO acceptance" in Path("scripts/native-acceptance.sh").read_text(encoding="utf-8")
    assert "v0.6.0 Native retry" in Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")


def test_v054_required_appearance_packages_have_a_separate_mandatory_plan():
    manifest = _manifest(
        packages=[
            {"name": "papirus-icon-theme", "provider": "apt", "required_for_appearance": True},
            {"name": "git", "provider": "apt", "required_for_appearance": False, "installer_visible": True},
        ]
    )
    assert native._profile_appearance_plan(manifest, "apt") == ["papirus-icon-theme"]
    apps, vendor, flatpaks = native._profile_app_plan(manifest, "apt")
    assert apps == ["git"]
    assert vendor == []
    assert flatpaks == []
    install = native.NATIVE_INSTALL_SCRIPT
    assert "appearance_pkgs=(__APPEARANCE_PACKAGES__)" in install
    assert "source appearance package(s) are unavailable" in install
    assert "required appearance package was not installed successfully" in install


def test_v054_known_snap_apps_resolve_to_flatpak_and_unknown_snap_blocks():
    known = _manifest(packages=[{"name": "code", "provider": "snap", "installer_visible": True}])
    apps, vendor, flatpaks = native._profile_app_plan(known, "apt")
    assert apps == []
    assert vendor == []
    assert flatpaks == ["com.visualstudio.code"]

    unknown = _manifest(packages=[{"name": "some-unknown-app", "provider": "snap", "installer_visible": True}])
    try:
        native._profile_app_plan(unknown, "apt")
    except native.NativeIsoError as exc:
        assert "no Native Pardus resolver" in str(exc)
    else:
        raise AssertionError("unknown Snap app must not silently leave a broken launcher")


def test_v054_invalid_package_tokens_are_rejected_before_shell_generation():
    manifest = _manifest(packages=[{"name": "--option", "provider": "apt", "installer_visible": True}])
    try:
        native._profile_app_plan(manifest, "apt")
    except native.NativeIsoError as exc:
        assert "invalid native package name" in str(exc)
    else:
        raise AssertionError("option-looking apt package token should be rejected")


def test_v054_build_keeps_errexit_and_uses_atomic_verified_output():
    text = native.NATIVE_BUILD_SCRIPT
    assert "restore_resolver() (" in text
    assert "cleanup_mounts() (" in text
    assert "cleanup_chroot() (" in text
    assert "trap - EXIT" not in text.split("cleanup_chroot\n# cleanup helpers", 1)[1]
    assert 'TMP_ISO="${OUT_ISO}.partial"' in text
    assert '-outdev "$TMP_ISO"' in text
    assert 'mv -f -- "$TMP_ISO" "$OUT_ISO"' in text
    assert "BUILD_FINISHED=1" in text
    assert "Rebuilt SquashFS failed structural validation" in text


def test_v054_build_preserves_boot_modes_and_uses_read_only_sysfs():
    text = native.NATIVE_BUILD_SCRIPT
    assert 'mount -t sysfs -o ro,nosuid,nodev,noexec sysfs "$ROOTFS/sys"' in text
    assert 'mount --rbind /sys "$ROOTFS/sys"' not in text
    assert "-report_el_torito plain -report_system_area plain" in text
    for token in ("BIOS", "UEFI", "MBR", "GPT", "APM"):
        assert token in text
    assert 'BASE_STAMP=$(stat -Lc' in text
    assert "Base ISO changed while the Native build was running" in text


def test_v054_build_preserves_squashfs_block_size_and_has_space_gate():
    text = native.NATIVE_BUILD_SCRIPT
    assert 'BLOCK_SIZE=$(awk' in text
    assert 'MKSQ_ARGS+=( -b "$BLOCK_SIZE" )' in text
    assert 'FREE_BYTES=$(df -PB1 "$WORK"' in text
    assert "Insufficient free space for Native remaster" in text
    assert "Generated filesystem.packages is empty" in text


def test_v054_stage_replaces_stale_profile_and_records_fingerprint(tmp_path: Path, monkeypatch):
    profile = _profile(tmp_path / "profile")
    base = tmp_path / "Pardus-25.2-XFCE-amd64.iso"
    base.write_bytes(b"fake")
    out = tmp_path / "out"
    stale = out / "profile/payload/home/stale.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("old secret-ish state", encoding="utf-8")

    monkeypatch.setattr(native, "probe_native_iso", lambda _p: _probe())
    native.stage_native_project(profile, base, out, result=tmp_path / "result")

    assert not stale.exists()
    restore = yaml.safe_load((out / "profile/native-restore.json").read_text(encoding="utf-8"))
    assert restore["schema"] == 2
    assert len(restore["profile_fingerprint"]) == 64
    assert "marker_matches(PRELOGIN_MARKER, fingerprint)" in (out / "native-first-login.py").read_text(encoding="utf-8")


def test_v054_profile_verification_rejects_payload_symlinks_and_traversal(tmp_path: Path):
    profile = _profile(tmp_path / "profile")
    outside = tmp_path / "outside.txt"
    outside.write_text("do not capture", encoding="utf-8")
    link = profile / "payload/home/leak.txt"
    link.symlink_to(outside)
    result = verify_profile(profile)
    assert not result.ok
    assert any("symbolic link" in item for item in result.errors)

    link.unlink()
    manifest = _manifest()
    manifest["desktop"]["configs"] = [
        {"destination": "{{HOME}}/../../outside.txt", "sha256": "deadbeef", "kind": "config"}
    ]
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    result = verify_profile(profile)
    assert not result.ok
    assert any("Non-portable payload destination" in item for item in result.errors)


def test_v054_acceptance_guards_destructive_paths():
    for rel in ("scripts/native-acceptance.sh", "scripts/retry-native-acceptance.sh"):
        text = Path(rel).read_text(encoding="utf-8")
        assert "guard_reset_dir()" in text
        assert '"${HOME:-/__no_home__}"' in text
        assert "rm -rf --" in text


def test_v054_pardus_adapter_is_explicitly_limited_to_25_x86_64():
    files = {"/live/filesystem.squashfs", "/live/vmlinuz", "/live/initrd.img"}
    p25 = native._probe_from_file_set(Path("Pardus-25.2-XFCE-amd64.iso"), files, "Pardus 25.2 XFCE amd64")
    assert p25.supports_native_build
    p26 = native._probe_from_file_set(Path("Pardus-26.0-XFCE-amd64.iso"), files, "Pardus 26.0 XFCE amd64")
    assert not p26.supports_native_build
    unknown_arch = native._probe_from_file_set(Path("Pardus-25.2-XFCE.iso"), files, "Pardus 25.2 XFCE")
    assert not unknown_arch.supports_native_build


def test_v054_boot_report_probe_is_a_hard_gate_not_best_effort():
    text = native.NATIVE_BUILD_SCRIPT
    assert 'if ! BASE_BOOT_REPORT=$(xorriso' in text
    assert 'if ! OUT_BOOT_REPORT=$(xorriso' in text
    assert 'BASE_BOOT_REPORT=$(xorriso' in text
    assert 'BASE_BOOT_REPORT=$(xorriso -indev "$BASE_ISO" -report_el_torito plain -report_system_area plain 2>&1 || true)' not in text


def test_v054_restore_is_single_user_and_does_not_follow_home_symlinks():
    prelogin = native.NATIVE_PRELOGIN
    first = native.NATIVE_FIRST_LOGIN
    assert 'TARGET_USER = Path("/var/lib/linux-iso/target-user")' in prelogin
    assert 'users[0] if users else None' in prelogin
    assert 'for entry in pwd.getpwall()' in prelogin  # candidate discovery only
    assert 'for entry in pwd.getpwall():\n        if not' in prelogin
    assert 'os.chown(path, uid, gid, follow_symlinks=False)' in prelogin
    assert 'if current.is_symlink()' in prelogin
    assert 'if dst.is_symlink()' in prelogin
    assert 'not is_target_user()' in first
    assert 'if current.is_symlink()' in first


def test_v054_system_visual_rejects_path_and_config_injection():
    ns = {"__name__": "suret_test"}
    exec(native.NATIVE_SYSTEM_VISUAL, ns)
    assert ns["safe_component_name"]("Nordic-cursors") == "Nordic-cursors"
    assert ns["safe_component_name"]("../../etc") is None
    assert ns["safe_component_name"]("theme\n[Autologin]") is None
    assert ns["safe_relative_file"]("theme.txt") == Path("theme.txt")
    assert ns["safe_relative_file"]("../etc/passwd") is None
    assert ns["safe_relative_file"]("/etc/passwd") is None
    assert ns["grub_assignment"]("GRUB_TIMEOUT", "5\nEVIL=1") is None


def test_v054_verifier_rejects_symlink_manifest_without_reading_target(tmp_path: Path):
    profile = tmp_path / "profile"
    profile.mkdir()
    external = tmp_path / "external.yaml"
    external.write_text(yaml.safe_dump(_manifest()), encoding="utf-8")
    (profile / "manifest.yaml").symlink_to(external)
    result = verify_profile(profile)
    assert not result.ok
    assert any("must not be a symbolic link" in item for item in result.errors)


def test_v054_host_bootstrap_covers_generated_build_helpers():
    bootstrap = Path("scripts/bootstrap-native-host.sh").read_text(encoding="utf-8")
    for token in (
        "[readlink]=coreutils", "[sha256sum]=coreutils", "[find]=findutils",
        "[xargs]=findutils", "[awk]=mawk", "[grep]=grep",
    ):
        assert token in bootstrap
    assert "sudo is required by Native ISO remaster operations" in bootstrap
    build = native.NATIVE_BUILD_SCRIPT
    for command in ("sha256sum", "awk", "grep", "find", "xargs", "sudo"):
        assert command in build.split("do need", 1)[0] or f'need "{command}"' in build


def test_v054_qemu_uses_exact_verified_native_iso_not_newest_iso():
    qemu = native.NATIVE_QEMU_SCRIPT
    assert 'ISO="$RESULT/__OUTPUT_NAME__"' in qemu
    assert "find \"$RESULT\"" not in qemu
    assert "sha256sum -c" in qemu
    assert 'OUT_SHA256=$(sha256sum "$OUT_ISO"' in native.NATIVE_BUILD_SCRIPT
    assert '"${OUT_ISO##*/}" > "$OUT_ISO.sha256"' in native.NATIVE_BUILD_SCRIPT


def test_v054_generated_templates_cannot_leave_unresolved_tokens():
    native._assert_template_rendered("ok", "value")
    try:
        native._assert_template_rendered("bad", "x=__MISSING_VALUE__")
    except native.NativeIsoError as exc:
        assert "__MISSING_VALUE__" in str(exc)
    else:
        raise AssertionError("unresolved template token must fail staging")


def test_v054_repack_has_post_install_space_model_and_success_cleanup():
    text = native.NATIVE_BUILD_SCRIPT
    assert "ORIG_SQUASH_BYTES=" in text
    assert "ORIG_ROOT_BYTES=" in text
    assert "NEW_ROOT_BYTES=" in text
    assert "EST_SQUASH_BYTES=" in text
    assert "REQUIRED_REPACK_BYTES=" in text
    assert "Insufficient free space after Native package growth" in text
    assert 'LINUX_ISO_KEEP_NATIVE_WORK:-0' in text
    assert 'sudo rm -rf --one-file-system -- "$WORK"' in text


def test_v054_capture_redacts_secret_assignments_in_generic_text(tmp_path: Path):
    from linux_iso import capture

    home = tmp_path / "home"
    src = home / ".config/example/settings.ini"
    src.parent.mkdir(parents=True)
    src.write_text("Theme=Nordic\nACCESS_TOKEN=super-secret\n", encoding="utf-8")
    dst = tmp_path / "profile/payload/home/.config/example/settings.ini"
    captured = capture._copy_file(src, dst, home, "config")
    text = dst.read_text(encoding="utf-8")
    assert "super-secret" not in text
    assert "redacted possible secret: ACCESS_TOKEN" in text
    assert captured.sanitized_lines == 1


def test_v054_sensitive_paths_are_casefolded_and_cover_browser_credentials():
    from linux_iso.security.sanitizer import path_is_sensitive

    assert path_is_sensitive(Path("/home/u/.config/Google-Chrome/Default/Cookies"))
    assert path_is_sensitive(Path("/home/u/.config/BraveSoftware/Brave-Browser/Login Data"))
    assert path_is_sensitive(Path("/home/u/.AWS/credentials"))
    assert not path_is_sensitive(Path("/home/u/.config/kdeglobals"))


def test_v054_system_visual_capture_does_not_follow_symlinks(tmp_path: Path):
    from linux_iso import capture

    source = tmp_path / "theme"
    source.mkdir()
    (source / "theme.conf").write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (source / "leak.txt").symlink_to(outside)
    destination = tmp_path / "captured"
    assert capture._copy_visual_tree(source, destination)
    assert (destination / "theme.conf").read_text(encoding="utf-8") == "safe"
    assert not (destination / "leak.txt").exists()


def test_v054_desktop_launcher_inline_credentials_are_redacted(tmp_path: Path):
    from linux_iso import capture

    home = tmp_path / "home"
    src = home / ".local/share/applications/private.desktop"
    src.parent.mkdir(parents=True)
    src.write_text(
        "[Desktop Entry]\nType=Application\nName=Private\n"
        "Exec=client --access-token=abc123 https://example.test/?refresh_token=xyz789\n",
        encoding="utf-8",
    )
    dst = tmp_path / "profile/payload/home/.local/share/applications/private.desktop"
    captured = capture._copy_file(src, dst, home, "launcher")
    text = dst.read_text(encoding="utf-8")
    assert "abc123" not in text
    assert "xyz789" not in text
    assert "--access-token=<redacted>" in text
    assert "refresh_token=<redacted>" in text
    assert captured.sanitized_lines == 2


def test_v054_destructive_paths_cannot_overlap_profile_result_or_base():
    build = native.NATIVE_BUILD_SCRIPT
    assert 'if path_within "$RESULT" "$WORK"' in build
    assert 'if path_within "$HERE" "$WORK"' in build
    assert 'if path_within "$PROFILE" "$WORK"' in build
    assert 'if path_within "$BASE_ISO" "$WORK"' in build
    for rel in ("scripts/native-acceptance.sh", "scripts/retry-native-acceptance.sh"):
        text = Path(rel).read_text(encoding="utf-8")
        assert "guard_native_layout()" in text
        assert 'path_within "$PROFILE" "$BUILD"' in text
        assert 'path_within "$PROFILE" "$RESULT"' in text
        assert 'path_within "$RESULT" "$BUILD"' in text
        assert 'path_within "$BUILD" "$RESULT"' in text
