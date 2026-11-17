from pathlib import Path
import types

import yaml

from linux_iso.builder.kiwi import _select_backend, generate_kiwi_project


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
            "custom_assets": [],
            "widgets": [],
            "widget_details": [],
            "component_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home", "asset_mode": "active"},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return profile


def test_v034_generated_build_prefers_container_and_blocks_sleep_only(tmp_path: Path):
    profile = _profile(tmp_path)
    out = tmp_path / "build"
    generate_kiwi_project(profile, out)
    text = (out / "build.sh").read_text(encoding="utf-8")
    assert "BACKEND=container" in text
    assert "direct KIWI container backend" in text
    assert "--entrypoint /usr/bin/kiwi-ng" in text
    assert "system build --description /description --target-dir /result" in text
    assert "system boxbuild --container" not in text
    assert "systemd-inhibit --what=sleep --mode=block" in text
    assert "sleep:idle" not in text
    assert "nice -n" in text
    assert "resource-monitor.log" in text
    assert "LINUX_ISO_KIWI_VERSION:-11.1.16" in text


def test_v034_auto_backend_prefers_uv_podman_container(monkeypatch):
    import linux_iso.builder.kiwi as kiwi
    monkeypatch.setattr(kiwi.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"uv", "podman", "kiwi-boxbuild"} else None)
    assert _select_backend("auto") == "container"


def test_v034_container_backend_requires_uv_and_podman(monkeypatch):
    import linux_iso.builder.kiwi as kiwi
    monkeypatch.setattr(kiwi.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "uv" else None)
    try:
        _select_backend("container")
    except Exception as exc:
        assert "podman" in str(exc)
    else:
        raise AssertionError("container backend should require podman")


def test_first_iso_uses_v034_report_names():
    text = Path("scripts/first-iso.sh").read_text(encoding="utf-8")
    assert "v038.txt" in text
    assert "v032.txt" not in text
