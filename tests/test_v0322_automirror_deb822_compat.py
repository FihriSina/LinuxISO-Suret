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
    patcher = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text()
    namespace = {"__name__": "linuxiso_runtime_patch_test"}
    exec(compile(patcher, "patch-calamares-runtime.py", "exec"), namespace)
    return build, namespace


def test_v0322_runtime_patch_inserts_compat_job_immediately_before_automirror(tmp_path: Path):
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
                            "mount",
                            "unpackfs",
                            "automirror",
                            "users",
                            "initramfs",
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
    compat_index = jobs.index("shellprocess@linuxiso_automirror_compat")
    assert jobs[compat_index + 1] == "automirror"
    assert jobs.count("shellprocess@linuxiso_automirror_compat") == 1
    assert any(
        item.get("id") == "linuxiso_automirror_compat"
        and item.get("module") == "shellprocess"
        and item.get("config") == "linuxiso_automirror_compat.conf"
        for item in data["instances"]
    )


def test_v0322_automirror_compat_only_creates_missing_legacy_sources_list(tmp_path: Path):
    build, _ = _runtime_namespace(tmp_path)
    patcher = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text()

    assert '"id": "linuxiso_automirror_compat"' in patcher
    assert '"dontChroot": True' in patcher
    assert '"mkdir -p ${ROOT}/etc/apt"' in patcher
    assert '"test -e ${ROOT}/etc/apt/sources.list || touch ${ROOT}/etc/apt/sources.list"' in patcher
    assert ": > ${ROOT}/etc/apt/sources.list" not in patcher


def test_v0322_automirror_instance_names_are_supported(tmp_path: Path):
    _, namespace = _runtime_namespace(tmp_path)
    etc = tmp_path / "etc-calamares"
    modules = etc / "modules"
    modules.mkdir(parents=True)
    settings = etc / "settings.conf"
    settings.write_text(
        yaml.safe_dump(
            {
                "instances": [],
                "sequence": [{"exec": ["automirror@ubuntu", "bootloader"]}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    namespace["SETTINGS"] = settings
    namespace["MODULES"] = modules
    namespace["patch_settings"]()

    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    assert data["sequence"][0]["exec"][:2] == [
        "shellprocess@linuxiso_automirror_compat",
        "automirror@ubuntu",
    ]
