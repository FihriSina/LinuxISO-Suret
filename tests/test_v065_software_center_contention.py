from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import linux_iso.builder.native as native
from linux_iso import __version__


def test_v065_version_and_qemu_marker():
    assert __version__ == "0.6.5"
    qemu = native.NATIVE_QEMU_SCRIPT
    assert "product=Suret-QEMU-Test" in qemu
    assert "version=0.6.5" in qemu


def test_v065_pardus_package_management_frontends_are_refreshed_from_official_sources_only():
    script = native.NATIVE_INSTALL_SCRIPT
    assert "for pkg in pardus-software pardus-update" in script
    assert 'install -y --only-upgrade "${package_ui_upgrades[@]}"' in script
    assert "Refreshing Pardus package-management UI from official Pardus 25 repositories" in script
    # The refresh must still live behind the isolated Pardus source configuration.
    assert script.index("configure_native_build_apt") < script.index("package_ui_upgrades=()")
    assert "depo.pardus.org.tr/pardus yirmibes" in script
    assert "deb.debian.org" not in script
    assert "archive.ubuntu.com" not in script


def test_v065_qemu_only_quiets_competing_update_autostarts_after_profile_restore():
    pre = native.NATIVE_PRELOGIN
    assert '== "Suret-QEMU-Test"' in pre
    assert 'Path("/etc/xdg/autostart")' in pre
    assert 'config_root.is_symlink() or target.is_symlink()' in pre
    assert '"pardus-update"' in pre
    assert '"package-update-indicator"' in pre
    assert '"discover-notifier"' in pre
    assert 'override.write_text("[Desktop Entry]\\nHidden=true\\n"' in pre
    # Captured autostarts must be restored first; the QEMU-only override wins last.
    assert pre.index("copy_profile(home") < pre.index("quiet_qemu_autostart(home")


def test_v065_first_login_suspends_only_acceptance_vm_background_indexers():
    first = native.NATIVE_FIRST_LOGIN
    assert '== "Suret-QEMU-Test"' in first
    assert '["balooctl6", "suspend"]' in first
    assert 'pardus-update([[:space:]]|$)' in first
    assert first.index("quiet_qemu_session()") < first.index("apply_appearance(data)")


def test_v065_native_pardus_launchers_are_still_restored_not_forced_to_discover(tmp_path: Path):
    profile = tmp_path / "profile"
    desktop = profile / "payload/home/.local/share/applications/pardus-software.desktop"
    desktop.parent.mkdir(parents=True)
    import base64
    original = "pardus-software"
    marker = base64.urlsafe_b64encode(original.encode()).decode()
    desktop.write_text(
        "[Desktop Entry]\nName=Pardus Yazılım Merkezi\n"
        "Exec=plasma-discover\n"
        f"X-Suret-Original-Exec-B64={marker}\n",
        encoding="utf-8",
    )
    count = native._restore_native_launcher_execs(profile)
    text = desktop.read_text(encoding="utf-8")
    assert count == 1
    assert "Exec=pardus-software" in text
    assert "plasma-discover" not in text
    assert "X-Suret-Original" not in text


def test_v065_generated_templates_are_syntax_valid():
    install = native.NATIVE_INSTALL_SCRIPT.replace("__DISTRO_ID__", "pardus")
    # Remaining placeholders are shell-array payloads and can be empty for syntax validation.
    for token in (
        "__VENDOR_ARCHIVE_APPS__", "__FLATPAKS__", "__REQUIRED_DESKTOP_PACKAGES__",
        "__OPTIONAL_DESKTOP_PACKAGES__", "__APPEARANCE_PACKAGES__", "__NATIVE_APT_PACKAGES__",
        "__VENDOR_APT_APPS__",
    ):
        install = install.replace(token, "")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "native-install.sh"
        path.write_text(install, encoding="utf-8")
        proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
