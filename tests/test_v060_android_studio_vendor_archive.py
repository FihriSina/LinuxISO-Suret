from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import yaml

from linux_iso import __version__
from linux_iso.builder import native


def _manifest(packages: list[dict]) -> dict:
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
        "packages": packages,
        "security": {"safe_mode": True},
        "restore": {
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "asset_mode": "active",
            "fidelity_schema": 10,
        },
    }


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


def _write_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "native-vendor-archive.py"
    helper.write_text(native.NATIVE_VENDOR_ARCHIVE_HELPER, encoding="utf-8")
    helper.chmod(0o755)
    return helper


def test_v060_version_and_acceptance_plan_include_vendor_archive():
    assert __version__ == "0.6.3"
    for path in (Path("scripts/retry-native-acceptance.sh"), Path("scripts/native-acceptance.sh")):
        text = path.read_text(encoding="utf-8")
        assert "v0.6.3" in text
        assert '("Vendor archive", "vendor_archive_apps")' in text


def test_v060_android_studio_true_flatpak_uses_vetted_vendor_archive():
    vendor, remaining = native._split_vendor_archive_flatpaks(
        ["com.google.AndroidStudio", "org.mozilla.firefox", "com.google.AndroidStudio"]
    )
    assert vendor == ["google-android-studio"]
    assert remaining == ["org.mozilla.firefox"]
    spec = native.VENDOR_ARCHIVE_FLATPAK_RESOLVERS["com.google.AndroidStudio"]
    assert spec["install_dir"] == "/opt/android-studio"
    assert spec["desktop_id"] == "com.google.AndroidStudio.desktop"


def test_v060_launcher_rewrite_is_scoped_to_android_studio_desktop(tmp_path: Path):
    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    apps.mkdir(parents=True)
    android = apps / "com.google.AndroidStudio.desktop"
    android.write_text(
        "[Desktop Entry]\nName=Android Studio\nTryExec=flatpak\n"
        "Exec=/usr/bin/flatpak run --branch=stable com.google.AndroidStudio %U\n",
        encoding="utf-8",
    )
    steam = apps / "com.valvesoftware.Steam.desktop"
    steam.write_text(
        "[Desktop Entry]\nName=Steam\nTryExec=flatpak\n"
        "Exec=flatpak run com.valvesoftware.Steam %U\n",
        encoding="utf-8",
    )

    count = native._rewrite_vendor_archive_launcher_execs(profile, {"google-android-studio"})
    assert count == 1
    android_text = android.read_text(encoding="utf-8")
    assert "Exec=/opt/android-studio/bin/studio %U" in android_text
    assert "TryExec=/opt/android-studio/bin/studio" in android_text
    steam_text = steam.read_text(encoding="utf-8")
    assert "TryExec=flatpak" in steam_text
    assert "Exec=flatpak run com.valvesoftware.Steam %U" in steam_text


def test_v060_metadata_parser_pairs_linux_filename_with_its_checksum_and_official_url(tmp_path: Path):
    helper = _write_helper(tmp_path)
    linux_sha = "a" * 64
    windows_sha = "b" * 64
    old_sha = "c" * 64
    filename = "android-studio-rabbit2-patch2-linux.tar.gz"
    page = tmp_path / "page.html"
    page.write_text(
        f"""
        <script>const linuxName = "{filename}";</script>
        <h2>Android Studio downloads</h2>
        <table>
          <tr><td>android-studio-rabbit2-patch2-windows.exe</td><td>{windows_sha}</td></tr>
          <tr><td>Linux</td><td>{filename}</td><td>1.6 GB</td><td>{linux_sha}</td></tr>
        </table>
        <a href="https://edgedl.me.gvt1.com/android/studio/ide-zips/2026.2.2.12/{filename}">download</a>
        <div>old dialog android-studio-quail2-linux.tar.gz {old_sha}</div>
        """,
        encoding="utf-8",
    )
    out = tmp_path / "meta.tsv"
    proc = subprocess.run(
        [str(helper), "parse-android-metadata", str(page), str(out)],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    url, sha, parsed_name = out.read_text(encoding="utf-8").strip().split("\t")
    assert parsed_name == filename
    assert sha == linux_sha
    assert url.startswith("https://edgedl.me.gvt1.com/")


def test_v060_metadata_parser_rejects_non_google_download_host(tmp_path: Path):
    helper = _write_helper(tmp_path)
    filename = "android-studio-rabbit2-patch2-linux.tar.gz"
    page = tmp_path / "page.html"
    page.write_text(
        "Android Studio downloads " + filename + " " + ("a" * 64) + " "
        + f"https://evil-gvt1.com/android/{filename}",
        encoding="utf-8",
    )
    out = tmp_path / "meta.tsv"
    proc = subprocess.run(
        [str(helper), "parse-android-metadata", str(page), str(out)],
        text=True,
        capture_output=True,
    )
    assert proc.returncode != 0
    assert not out.exists()


def _add_tar_file(tf: tarfile.TarFile, name: str, data: bytes = b"x", mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    tf.addfile(info, io.BytesIO(data))


def test_v060_android_archive_helper_extracts_only_safe_android_studio_tree(tmp_path: Path):
    helper = _write_helper(tmp_path)
    good = tmp_path / "good.tar.gz"
    with tarfile.open(good, "w:gz") as tf:
        _add_tar_file(tf, "android-studio/bin/studio", b"#!/bin/sh\n", 0o755)
        _add_tar_file(tf, "android-studio/bin/studio.svg", b"<svg/>\n")
    root = tmp_path / "root"
    root.mkdir()
    proc = subprocess.run(
        [str(helper), "extract-android", str(good), str(root)],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (root / "android-studio/bin/studio").is_file()

    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        _add_tar_file(tf, "../escape", b"owned")
    bad_root = tmp_path / "bad-root"
    bad_root.mkdir()
    proc = subprocess.run(
        [str(helper), "extract-android", str(bad), str(bad_root)],
        text=True,
        capture_output=True,
    )
    assert proc.returncode != 0
    assert not (tmp_path / "escape").exists()


def test_v060_android_archive_helper_rejects_escaping_symlink_and_setuid(tmp_path: Path):
    helper = _write_helper(tmp_path)
    bad_link = tmp_path / "bad-link.tar.gz"
    with tarfile.open(bad_link, "w:gz") as tf:
        link = tarfile.TarInfo("android-studio/bin/outside")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../etc/passwd"
        tf.addfile(link)
    root = tmp_path / "root-link"
    root.mkdir()
    proc = subprocess.run([str(helper), "extract-android", str(bad_link), str(root)], capture_output=True, text=True)
    assert proc.returncode != 0

    privileged = tmp_path / "setuid.tar.gz"
    with tarfile.open(privileged, "w:gz") as tf:
        _add_tar_file(tf, "android-studio/bin/studio", b"x", 0o4755)
    root2 = tmp_path / "root-setuid"
    root2.mkdir()
    proc = subprocess.run([str(helper), "extract-android", str(privileged), str(root2)], capture_output=True, text=True)
    assert proc.returncode != 0


def test_v060_stage_moves_android_studio_out_of_flatpak_and_renders_safe_helper(tmp_path: Path, monkeypatch):
    profile = tmp_path / "profile"
    apps = profile / "payload/home/.local/share/applications"
    apps.mkdir(parents=True)
    launcher = apps / "com.google.AndroidStudio.desktop"
    launcher.write_text(
        "[Desktop Entry]\nName=Android Studio\nTryExec=/usr/bin/flatpak\n"
        "Exec=/usr/bin/flatpak run com.google.AndroidStudio %F\n",
        encoding="utf-8",
    )
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(
            _manifest([
                {"name": "git", "provider": "apt", "installer_visible": True},
                {"name": "com.google.AndroidStudio", "provider": "flatpak", "installer_visible": True},
            ]),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native, "probe_native_iso", lambda _p: _probe())
    monkeypatch.setattr(native, "verify_profile", lambda _p: type("R", (), {"ok": True})())
    base = tmp_path / "Pardus-25.2-XFCE-amd64.iso"
    base.write_bytes(b"fake")
    out = tmp_path / "native-build"
    native.stage_native_project(profile, base, out, result=tmp_path / "result")

    meta = json.loads((out / "native.json").read_text(encoding="utf-8"))
    install = (out / "native-install.sh").read_text(encoding="utf-8")
    build = (out / "build-native.sh").read_text(encoding="utf-8")
    rendered_launcher = (out / "profile/payload/home/.local/share/applications/com.google.AndroidStudio.desktop").read_text(encoding="utf-8")
    helper = out / "native-vendor-archive.py"

    assert meta["vendor_archive_apps"] == ["google-android-studio"]
    assert meta["flatpaks"] == []
    assert "vendor_archive_apps=(google-android-studio)" in install
    assert "flatpaks=()" in install
    assert "/var/tmp/linux-iso-vendor/android-studio" in install
    assert "/run/linux-iso/apt-build/android-studio" not in install
    assert "sha256sum" in install
    assert "parse-android-metadata" in install
    assert "extract-android" in install
    assert "native-vendor-archive.py" in build
    assert helper.is_file() and os.access(helper, os.X_OK)
    assert "Exec=/opt/android-studio/bin/studio %F" in rendered_launcher
    assert "TryExec=/opt/android-studio/bin/studio" in rendered_launcher
    assert "com.google.AndroidStudio" not in meta["flatpaks"]
    assert "__VENDOR_ARCHIVE_APPS__" not in install

    subprocess.run(["bash", "-n", out / "native-install.sh"], check=True)
    subprocess.run(["bash", "-n", out / "build-native.sh"], check=True)
    subprocess.run(["python3", "-m", "py_compile", helper], check=True)
