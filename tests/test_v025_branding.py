from __future__ import annotations

from pathlib import Path

import yaml

from linux_iso.branding import CODENAME, PACKAGE_NAME, PRODUCT_NAME
from linux_iso.installer.catalog import build_catalog
from linux_iso.planner import audit


def _minimal_profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    profile.mkdir()
    manifest = {
        "source": {"distro_name": "Test"},
        "desktop": {
            "desktop": "kde-plasma",
            "custom_assets": [],
            "widget_details": [],
            "component_details": [],
        },
        "packages": [],
        "security": {"safe_mode": True, "excluded": [], "notes": []},
    }
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return profile


def test_product_branding_is_ascii_safe():
    assert PACKAGE_NAME == "linux-iso"
    assert PRODUCT_NAME == "Linux ISO - Suret"
    assert CODENAME == "Suret"
    assert PRODUCT_NAME.isascii()
    assert CODENAME.isascii()


def test_product_branding_is_used_in_user_facing_outputs(tmp_path: Path):
    profile = _minimal_profile(tmp_path)
    assert audit(profile).startswith(f"{PRODUCT_NAME} profile audit")
    assert build_catalog(profile)["product"] == PRODUCT_NAME
