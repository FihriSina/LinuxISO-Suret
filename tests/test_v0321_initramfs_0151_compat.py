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


def test_v0321_runtime_patch_replaces_calamares_initramfs_job(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    patcher = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text()

    namespace = {"__name__": "linuxiso_runtime_patch_test"}
    exec(compile(patcher, "patch-calamares-runtime.py", "exec"), namespace)

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
                            "users",
                            "initramfs",
                            "shellprocess@before_bootloader_kerncopy",
                            "contextualprocess@before_bootloader",
                            "bootloader",
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

    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    jobs = data["sequence"][0]["exec"]
    assert "initramfs" not in jobs
    assert "shellprocess@linuxiso_initramfs" in jobs
    assert "shellprocess@linuxiso_before_bootloader_kerncopy" in jobs
    assert "contextualprocess@before_bootloader" not in jobs
    assert any(
        item.get("id") == "linuxiso_initramfs"
        and item.get("module") == "shellprocess"
        and item.get("config") == "linuxiso_initramfs.conf"
        for item in data["instances"]
    )


def test_v0321_target_initramfs_helper_never_uses_removed_takeover_flag(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    helper_path = build / "root/usr/lib/linux-iso/update-target-initramfs"
    helper = helper_path.read_text(encoding="utf-8")

    assert helper_path.stat().st_mode & 0o111
    assert "update-initramfs -c -k" in helper
    assert "update-initramfs -u -k" in helper
    assert "update-initramfs -c -t" not in helper
    assert "update-initramfs -t" not in helper
    assert "/lib/modules/*" in helper


def test_v0321_runtime_module_runs_initramfs_helper_inside_target(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    patcher = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text()

    assert '"id": "linuxiso_initramfs"' in patcher
    assert '"config": "linuxiso_initramfs.conf"' in patcher
    assert '"dontChroot": False' in patcher
    assert '"script": ["/usr/lib/linux-iso/update-target-initramfs"]' in patcher
