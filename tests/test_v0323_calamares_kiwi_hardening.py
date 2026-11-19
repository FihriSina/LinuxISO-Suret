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


def _runtime_namespace(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    patcher = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text(
        encoding="utf-8"
    )
    namespace = {"__name__": "linuxiso_runtime_patch_test"}
    exec(compile(patcher, "patch-calamares-runtime.py", "exec"), namespace)
    return build, namespace


def test_v0323_replaces_kubuntu_live_iso_jobs_with_suret_finalizer(tmp_path: Path):
    _, namespace = _runtime_namespace(tmp_path)
    etc = tmp_path / "etc-calamares"
    modules = etc / "modules"
    modules.mkdir(parents=True)
    settings = etc / "settings.conf"
    settings.write_text(
        yaml.safe_dump(
            {
                "instances": [],
                "sequence": [
                    {
                        "show": [
                            "welcome",
                            "locale",
                            "keyboard",
                            "pkgselect",
                            "partition",
                            "users",
                            "packagechooser@linuxiso_internet",
                            "summary",
                        ]
                    },
                    {
                        "exec": [
                            "partition",
                            "mount",
                            "unpackfs",
                            "machineid",
                            "fstab",
                            "locale",
                            "keyboard",
                            "localecfg",
                            "luksbootkeyfile",
                            "users",
                            "linuxiso-install",
                            "displaymanager",
                            "networkcfg",
                            "hwclock",
                            "automirror",
                            "shellprocess@before_bootloader_kerncopy",
                            "shellprocess@bug-LP#1829805",
                            "shellprocess@fixconkeys_part1",
                            "shellprocess@fixconkeys_part2",
                            "initramfs",
                            "contextualprocess@before_bootloader",
                            "bootloader",
                            "shellprocess@add386arch",
                            "packages",
                            "pkgselectprocess@pkgselectprocess",
                            "contextualprocess@pkgselect_action",
                            "contextualprocess@pkgselect_snap_action",
                            "shellprocess@rmcdrom",
                            "shellprocess@logs",
                            "umount",
                        ]
                    },
                    {"show": ["finished"]},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    namespace["SETTINGS"] = settings
    namespace["MODULES"] = modules
    namespace["patch_settings"]()

    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    show = data["sequence"][0]["show"]
    jobs = data["sequence"][1]["exec"]

    assert "pkgselect" not in show
    assert "packagechooser@linuxiso_internet" in show

    assert "packages" not in jobs
    assert "shellprocess@add386arch" not in jobs
    assert "pkgselectprocess@pkgselectprocess" not in jobs
    assert "contextualprocess@pkgselect_action" not in jobs
    assert "contextualprocess@pkgselect_snap_action" not in jobs
    assert "shellprocess@rmcdrom" not in jobs
    assert "shellprocess@logs" not in jobs
    assert "contextualprocess@before_bootloader" not in jobs

    assert "shellprocess@linuxiso_before_bootloader_kerncopy" in jobs
    assert "shellprocess@linuxiso_initramfs" in jobs
    assert "shellprocess@linuxiso_automirror_compat" in jobs
    assert "automirror" in jobs
    assert "shellprocess@fixconkeys_part1" in jobs
    assert "shellprocess@fixconkeys_part2" in jobs
    assert "bootloader" in jobs
    assert "linuxiso-install" in jobs
    assert "umount" in jobs

    finalizer = "shellprocess@linuxiso_target_finalize"
    assert jobs.count(finalizer) == 1
    assert jobs.index(finalizer) < jobs.index("umount")
    assert any(
        item.get("id") == "linuxiso_target_finalize"
        and item.get("module") == "shellprocess"
        and item.get("config") == "linuxiso_target_finalize.conf"
        for item in data["instances"]
    )


def test_v0323_instanced_packages_job_is_replaced_and_finalizer_is_idempotent(tmp_path: Path):
    _, namespace = _runtime_namespace(tmp_path)
    etc = tmp_path / "etc-calamares"
    modules = etc / "modules"
    modules.mkdir(parents=True)
    settings = etc / "settings.conf"
    settings.write_text(
        yaml.safe_dump(
            {
                "instances": [],
                "sequence": [
                    {
                        "exec": [
                            "automirror@ubuntu",
                            "packages@cleanup",
                            "shellprocess@linuxiso_target_finalize",
                            "umount",
                        ]
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    namespace["SETTINGS"] = settings
    namespace["MODULES"] = modules
    namespace["patch_settings"]()

    jobs = yaml.safe_load(settings.read_text(encoding="utf-8"))["sequence"][0]["exec"]
    assert "packages@cleanup" not in jobs
    assert jobs.count("shellprocess@linuxiso_target_finalize") == 1
    assert jobs[:2] == ["shellprocess@linuxiso_automirror_compat", "automirror@ubuntu"]


def test_v0323_target_finalizer_is_offline_safe_and_strips_live_credentials(tmp_path: Path):
    build, _ = _runtime_namespace(tmp_path)
    finalizer_path = build / "root/usr/lib/linux-iso/finalize-target"
    finalizer = finalizer_path.read_text(encoding="utf-8")

    assert finalizer_path.stat().st_mode & 0o111
    assert "apt-get" not in finalizer
    assert "dpkg" not in finalizer
    assert "/etc/sddm.conf.d/99-linux-iso-live.conf" in finalizer
    assert "/etc/sudoers.d/99-linux-iso-live" in finalizer
    assert "target-username" in finalizer
    assert "userdel -r live" in finalizer
    assert "passwd -l live" in finalizer
    assert "/etc/apt/sources.list.d/cdrom.sources" in finalizer
    assert "/usr/bin/linux-iso-installer" in finalizer


def test_v0323_profile_job_records_target_username_for_safe_live_user_cleanup(tmp_path: Path):
    build, _ = _runtime_namespace(tmp_path)
    job = (
        build / "root/usr/share/linux-iso/calamares/modules/linuxiso-install/main.py"
    ).read_text(encoding="utf-8")

    assert 'root / "var/lib/linux-iso/target-username"' in job
    assert 'marker.write_text(str(username) + "\\n"' in job
