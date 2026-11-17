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


def test_v038_build_uses_sibling_result_dir_and_artifact_gate(tmp_path: Path):
    profile = _profile(tmp_path)
    build = tmp_path / "linux-iso-build"
    generate_kiwi_project(profile, build)
    text = (build / "build.sh").read_text(encoding="utf-8")
    assert 'OUT=${1:-${LINUX_ISO_RESULT_DIR:-${HERE}-result}}' in text
    assert "Refusing nested KIWI target dir" in text
    assert "no ISO artifact was created" in text
    assert "kiwi-preflight.log" in text
    assert "--logfile stdout image info" in text


def test_v038_first_iso_uses_sibling_result_dir():
    text = Path("scripts/first-iso.sh").read_text(encoding="utf-8")
    assert 'RESULT_DIR=${LINUX_ISO_RESULT_DIR:-${BUILD_DIR}-result}' in text
    assert 'rm -rf "$RESULT_DIR"' in text
    assert '"$BUILD_DIR/build.sh" "$RESULT_DIR"' in text
    assert "v038.txt" in text
