from pathlib import Path
import json
import yaml

from linux_iso.builder.kiwi import generate_kiwi_project, UBUNTU_2604_KDE


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    (profile / "payload/home").mkdir(parents=True)
    (profile / "payload/system/grub/theme").mkdir(parents=True)
    (profile / "payload/system/grub/theme/theme.txt").write_text("title-text: source\n", encoding="utf-8")
    (profile / "payload/system/sddm/theme").mkdir(parents=True)
    (profile / "payload/system/sddm/theme/Main.qml").write_text("// source theme\n", encoding="utf-8")
    (profile / "system-visual.json").write_text(json.dumps({
        "schema": 1,
        "grub": {"theme_captured": True, "theme_file": "theme.txt", "settings": {"GRUB_GFXMODE": "1920x1080", "GRUB_TIMEOUT_STYLE": "menu", "GRUB_TIMEOUT": "5"}},
        "sddm": {"theme_captured": True, "settings": {"Current": "pardus", "CursorTheme": "Breeze_Light"}},
    }), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source": {"distro_id": "pardus", "distro_name": "Pardus GNU/Linux 25", "distro_name_short": "Pardus GNU/Linux", "distro_version": "25", "architecture": "x86_64"},
        "desktop": {"desktop": "kde-plasma", "configs": [], "custom_assets": [], "widgets": [], "user_plasmoids": [], "widget_details": [], "component_details": []},
        "packages": [], "security": {"safe_mode": True},
        "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home", "asset_mode": "active", "fidelity_schema": 8},
    }
    (profile / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return profile


def test_v0332_recipe_contains_kio_extras_for_computer_kio():
    assert "kio-extras" in UBUNTU_2604_KDE.image_packages


def test_v0332_target_profile_applies_grub_sddm_avatar_and_env(tmp_path: Path):
    build = tmp_path / "build"
    generate_kiwi_project(_profile(tmp_path), build)
    target = (build / "root/usr/lib/linux-iso/apply-target-profile.py").read_text(encoding="utf-8")
    assert "98-linux-iso-source-fidelity.cfg" in target
    assert "/usr/share/grub/themes/suret-source" in target
    assert "98-linux-iso-source-fidelity.conf" in target
    assert "usr/share/sddm/themes/suret-source" in target
    assert 'home / ".local/bin/env"' in target
    assert "AccountsService/icons" in target
    finalizer = (build / "root/usr/lib/linux-iso/finalize-target").read_text(encoding="utf-8")
    assert "update-grub" in finalizer
    assert "grub-mkconfig" in finalizer
