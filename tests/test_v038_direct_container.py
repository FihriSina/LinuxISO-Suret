from pathlib import Path

import yaml

from linux_iso.builder.kiwi import generate_kiwi_project


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    payload = profile / "payload/home/.config"
    payload.mkdir(parents=True)
    (payload / "kdeglobals").write_text("[Icons]\nTheme=Breeze\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "distro_name": "Pardus", "architecture": "x86_64"},
        "desktop": {
            "desktop": "kde-plasma",
            "configs": [{"source": "{{HOME}}/.config/kdeglobals", "destination": "{{HOME}}/.config/kdeglobals", "kind": "desktop-config", "sha256": None}],
            "custom_assets": [], "widgets": [], "widget_details": [], "component_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return profile


def test_v038_container_backend_runs_kiwi_directly(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)
    text = (build / "build.sh").read_text(encoding="utf-8")
    assert "registry.opensuse.org/virtualization/appliances/selfcontained/${BOX}/images/${BOX}:latest" in text
    assert "--entrypoint /usr/bin/kiwi-ng" in text
    assert "system build --description /description --target-dir /result" in text
    assert '--volume \"$HERE:/description:ro\"' in text
    assert '--volume \"$OUT:/result\"' in text
    assert "system boxbuild --container" not in text


def test_v038_container_backend_restores_result_ownership(tmp_path: Path):
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(_profile(tmp_path), build)
    text = (build / "build.sh").read_text(encoding="utf-8")
    assert "sudo chown -R" in text
    assert '$(id -u):$(id -g)' in text


def test_v038_container_backend_does_not_require_kvm(monkeypatch):
    import types
    import linux_iso.buildenv as env
    monkeypatch.setattr(env, "parse_os_release", lambda: {"ID": "pardus", "PRETTY_NAME": "Pardus"})
    monkeypatch.setattr(env.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(env, "_tool", lambda name: f"/usr/bin/{name}" if name in {"uv", "podman", "kiwi-boxbuild", "qemu-system-x86_64"} else None)
    monkeypatch.setattr(env, "_kvm_accessible", lambda: (False, "/dev/kvm exists but the current user cannot read/write it"))
    monkeypatch.setattr(env.shutil, "disk_usage", lambda _: types.SimpleNamespace(total=50 * 1024**3, used=10 * 1024**3, free=40 * 1024**3))
    report = env.build_host_report()
    assert report.ready is True
    assert report.recommended_backend == "container"
    assert not any("VM boxbuild cannot use hardware acceleration" in item for item in report.warnings)
