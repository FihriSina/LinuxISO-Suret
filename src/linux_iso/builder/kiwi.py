from __future__ import annotations

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from linux_iso import __version__
from linux_iso.branding import PRODUCT_NAME
from linux_iso.verification import verify_profile
from linux_iso.builder.calamares import generate_calamares_overlay


class BuilderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AptRepository:
    alias: str
    url: str
    distribution: str
    components: str
    signing_key: str | None = None


@dataclass(frozen=True)
class BaseRecipe:
    id: str
    image_name: str
    native_provider: str
    repositories: tuple[AptRepository, ...]
    bootstrap_packages: tuple[str, ...]
    image_packages: tuple[str, ...]
    target_plasma_version: str | None = None
    preferred_box: str = "ubuntu"


UBUNTU_2604_KDE = BaseRecipe(
    id="ubuntu-26.04-kde",
    image_name="linux-iso-suret-ubuntu-26.04",
    native_provider="apt",
    repositories=(
        AptRepository(
            "ubuntu",
            "http://archive.ubuntu.com/ubuntu",
            "resolute",
            "main restricted universe multiverse",
            "https://archive.ubuntu.com/ubuntu/project/ubuntu-archive-keyring.gpg",
        ),
        AptRepository(
            "ubuntu-updates",
            "http://archive.ubuntu.com/ubuntu",
            "resolute-updates",
            "main restricted universe multiverse",
            "https://archive.ubuntu.com/ubuntu/project/ubuntu-archive-keyring.gpg",
        ),
        AptRepository(
            "ubuntu-security",
            "http://security.ubuntu.com/ubuntu",
            "resolute-security",
            "main restricted universe multiverse",
            "https://archive.ubuntu.com/ubuntu/project/ubuntu-archive-keyring.gpg",
        ),
    ),
    bootstrap_packages=(
        "base-files",
        "base-passwd",
        "bash",
        "coreutils",
        "dpkg",
        "apt",
        "libc6",
        "systemd-sysv",
    ),
    image_packages=(
        "ca-certificates",
        "locales-all",
        "linux-generic",
        "kubuntu-desktop",
        "calamares",
        "calamares-settings-kubuntu",
        "dosfstools",
        "e2fsprogs",
        "parted",
        "rsync",
        "kiwi-dracut-live",
        "grub-pc-bin",
        "grub-efi-amd64-bin",
        "grub2-common",
        "efibootmgr",
        "plasma-session-x11",
        "kwin-x11",
        "xorg",
        "konsole",
        "python3",
        "sudo",
        "network-manager",
        "sddm",
    ),
    target_plasma_version="6.6",
    preferred_box="ubuntu",
)

RECIPES = {UBUNTU_2604_KDE.id: UBUNTU_2604_KDE}


PATCH_CALAMARES = r'''#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import yaml

SETTINGS = Path("/etc/calamares/settings.conf")
FRAGMENT = Path("/etc/calamares/linux-iso-settings-fragment.yaml")


def insert_unique(items, values, before=None, after=None):
    for value in values:
        if value in items:
            continue
        if before in items:
            items.insert(items.index(before), value)
        elif after in items:
            items.insert(items.index(after) + 1, value)
        else:
            items.append(value)


def main():
    if not SETTINGS.is_file() or not FRAGMENT.is_file():
        raise SystemExit("Calamares settings or Linux ISO fragment missing")
    settings = yaml.safe_load(SETTINGS.read_text(encoding="utf-8")) or {}
    fragment = yaml.safe_load(FRAGMENT.read_text(encoding="utf-8")) or {}

    if fragment.get("branding"):
        settings["branding"] = fragment["branding"]

    modules_search = settings.setdefault("modules-search", ["local"])
    custom_modules = "/usr/share/linux-iso/calamares/modules"
    if custom_modules not in modules_search:
        modules_search.append(custom_modules)

    instances = settings.setdefault("instances", [])
    existing = {(x.get("module"), x.get("id")) for x in instances if isinstance(x, dict)}
    for item in fragment.get("instances", []):
        key = (item.get("module"), item.get("id"))
        if key not in existing:
            instances.append(item)
            existing.add(key)

    patch = fragment.get("sequence_patch", {})
    chooser = patch.get("insert_before_summary", [])
    jobs = patch.get("insert_in_exec_after_users", [])
    for phase in settings.get("sequence", []):
        if not isinstance(phase, dict):
            continue
        if "show" in phase and "summary" in phase["show"]:
            insert_unique(phase["show"], chooser, before="summary")
        if "exec" in phase and "users" in phase["exec"]:
            # Preserve the fragment's declared order. Repeatedly inserting at
            # index(users)+1 would reverse netinstall jobs and could run the
            # mixed-provider installer before the checkbox state is published.
            position = phase["exec"].index("users") + 1
            for job in jobs:
                if job in phase["exec"]:
                    phase["exec"].remove(job)
                phase["exec"].insert(position, job)
                position += 1

    SETTINGS.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
'''


RUNTIME_CALAMARES_PATCH = r'''#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import yaml

SETTINGS = Path("/etc/calamares/settings.conf")
MODULES = Path("/etc/calamares/modules")


def patch_text_configs(source: str, kernel: str) -> None:
    replacements = {
        "/cdrom/casper/filesystem.squashfs": source,
        "/cdrom/casper/vmlinuz": kernel,
    }
    for base in (Path("/etc/calamares"), Path("/usr/share/calamares")):
        if not base.is_dir():
            continue
        for path in base.rglob("*.conf"):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            updated = text
            for old, new in replacements.items():
                updated = updated.replace(old, new)
            if updated != text:
                path.write_text(updated, encoding="utf-8")


def patch_branding_text() -> None:
    for base in (Path("/etc/calamares/branding"), Path("/usr/share/calamares/branding")):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            # Never rewrite the generated source-native branding component; a
            # Kubuntu source profile must remain Kubuntu, Pardus must remain
            # Pardus, etc. This replacement exists only for hidden legacy
            # distro branding files that are no longer selected by Suret.
            if "linuxiso-source" in path.parts:
                continue
            if not path.is_file() or path.suffix.lower() not in {".desc", ".conf", ".txt", ".html", ".qml"}:
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                text = path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeDecodeError):
                continue
            updated = text.replace("Kubuntu", "Linux ISO - Suret")
            if updated != text:
                path.write_text(updated, encoding="utf-8")


def patch_settings() -> None:
    settings = yaml.safe_load(SETTINGS.read_text(encoding="utf-8")) or {}
    settings["branding"] = "linuxiso-source"
    instances = settings.setdefault("instances", [])
    wanted_instances = (
        {
            "id": "linuxiso_before_bootloader_kerncopy",
            "module": "shellprocess",
            "config": "linuxiso_before_bootloader_kerncopy.conf",
        },
        {
            "id": "linuxiso_initramfs",
            "module": "shellprocess",
            "config": "linuxiso_initramfs.conf",
        },
        {
            "id": "linuxiso_automirror_compat",
            "module": "shellprocess",
            "config": "linuxiso_automirror_compat.conf",
        },
        {
            "id": "linuxiso_apply_target_profile",
            "module": "shellprocess",
            "config": "linuxiso_apply_target_profile.conf",
        },
        {
            "id": "linuxiso_target_finalize",
            "module": "shellprocess",
            "config": "linuxiso_target_finalize.conf",
        },
    )
    for wanted in wanted_instances:
        if not any(
            isinstance(item, dict)
            and item.get("module") == wanted["module"]
            and item.get("id") == wanted["id"]
            for item in instances
        ):
            instances.append(wanted)

    def is_pkgselect_show(item):
        return isinstance(item, str) and (item == "pkgselect" or item.startswith("pkgselect@"))

    def is_users_exec(item):
        return isinstance(item, str) and (item == "users" or item.startswith("users@"))

    def is_linuxiso_selection_exec(item):
        return isinstance(item, str) and item.startswith("netinstall@linuxiso_")

    def is_ubuntu_live_only_exec(item):
        if not isinstance(item, str):
            return False
        return (
            item == "shellprocess@add386arch"
            or item == "shellprocess@rmcdrom"
            or item == "shellprocess@logs"
            or item == "pkgselectprocess"
            or item.startswith("pkgselectprocess@")
            or item.startswith("contextualprocess@pkgselect")
        )

    profile_job = "shellprocess@linuxiso_apply_target_profile"
    install_job = "linuxiso-install"
    finalizer = "shellprocess@linuxiso_target_finalize"
    profile_inserted = False
    install_inserted = False
    finalizer_inserted = False
    last_exec_phase = None
    for phase in settings.get("sequence", []):
        if not isinstance(phase, dict):
            continue

        if isinstance(phase.get("show"), list):
            phase["show"] = [item for item in phase["show"] if not is_pkgselect_show(item)]

        if not isinstance(phase.get("exec"), list):
            continue
        last_exec_phase = phase
        has_selection_jobs = any(is_linuxiso_selection_exec(item) for item in phase["exec"])
        patched = []
        for item in phase["exec"]:
            if is_ubuntu_live_only_exec(item):
                continue
            if isinstance(item, str) and (item == "automirror" or item.startswith("automirror@")):
                compat = "shellprocess@linuxiso_automirror_compat"
                if compat not in patched:
                    patched.append(compat)
            if item == "shellprocess@before_bootloader_kerncopy":
                item = "shellprocess@linuxiso_before_bootloader_kerncopy"
            if isinstance(item, str) and (item == "initramfs" or item.startswith("initramfs@")):
                item = "shellprocess@linuxiso_initramfs"
            if isinstance(item, str) and (item == "packages" or item.startswith("packages@")):
                item = finalizer
            if item == "contextualprocess@before_bootloader":
                continue

            # Always apply the captured desktop after Calamares has created the
            # real user, independently of the optional application installer.
            if item == install_job and profile_job not in patched:
                patched.append(profile_job)
                profile_inserted = True
            if item not in patched:
                patched.append(item)
            if is_users_exec(item):
                if profile_job not in patched:
                    patched.append(profile_job)
                profile_inserted = True
                # Legacy v0.3.27 netinstall instances had exec jobs. v0.3.28+
                # packagechooserq writes selection state during the show phase
                # and therefore needs no exec selector. Keep this ordering code
                # only for backwards-compatible media.
                if not has_selection_jobs and install_job not in patched:
                    patched.append(install_job)
                    install_inserted = True
            elif item == install_job:
                install_inserted = True

        if has_selection_jobs and install_job not in patched:
            selection_positions = [
                i for i, value in enumerate(patched) if is_linuxiso_selection_exec(value)
            ]
            if selection_positions:
                patched.insert(selection_positions[-1] + 1, install_job)
                install_inserted = True

        # Some flavor configurations rename/instance the users module.  If no
        # direct anchor was found, place profile+app jobs before display-manager
        # or other late target jobs rather than silently skipping fidelity.
        if not profile_inserted:
            anchors = [
                i for i, value in enumerate(patched)
                if isinstance(value, str) and (
                    value == "displaymanager"
                    or value.startswith("displaymanager@")
                    or value == "networkcfg"
                    or value.startswith("networkcfg@")
                    or value == finalizer
                    or value == "umount"
                )
            ]
            if anchors:
                pos = anchors[0]
                patched.insert(pos, profile_job)
                if install_job not in patched:
                    patched.insert(pos + 1, install_job)
                profile_inserted = True
                install_inserted = True

        if finalizer in patched:
            finalizer_inserted = True
        elif not finalizer_inserted and "umount" in patched:
            patched.insert(patched.index("umount"), finalizer)
            finalizer_inserted = True
        phase["exec"] = patched

    if last_exec_phase is not None:
        if not profile_inserted:
            last_exec_phase["exec"].append(profile_job)
            profile_inserted = True
        if not install_inserted:
            last_exec_phase["exec"].append(install_job)
            install_inserted = True
        if not finalizer_inserted:
            last_exec_phase["exec"].append(finalizer)

    SETTINGS.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch-calamares-runtime.py SOURCE_SQUASHFS KERNEL_SOURCE")
    source, kernel = sys.argv[1], sys.argv[2]
    MODULES.mkdir(parents=True, exist_ok=True)
    kerncopy = {
        "dontChroot": True,
        "timeout": 30,
        "script": [
            "mkdir -pv ${ROOT}/boot",
            f"test -e ${{ROOT}}/boot/vmlinuz-$(uname -r) || cp {kernel} ${{ROOT}}/boot/vmlinuz-$(uname -r)",
        ],
    }
    (MODULES / "linuxiso_before_bootloader_kerncopy.conf").write_text(
        yaml.safe_dump(kerncopy, sort_keys=False),
        encoding="utf-8",
    )
    initramfs = {
        "dontChroot": False,
        "timeout": 300,
        "verbose": True,
        "script": ["/usr/lib/linux-iso/update-target-initramfs"],
    }
    (MODULES / "linuxiso_initramfs.conf").write_text(
        yaml.safe_dump(initramfs, sort_keys=False),
        encoding="utf-8",
    )
    automirror_compat = {
        "dontChroot": True,
        "timeout": 30,
        "script": [
            "mkdir -p ${ROOT}/etc/apt",
            "test -e ${ROOT}/etc/apt/sources.list || touch ${ROOT}/etc/apt/sources.list",
        ],
    }
    (MODULES / "linuxiso_automirror_compat.conf").write_text(
        yaml.safe_dump(automirror_compat, sort_keys=False),
        encoding="utf-8",
    )
    apply_target_profile = {
        "dontChroot": True,
        "timeout": 120,
        "verbose": True,
        "script": ["python3 /usr/lib/linux-iso/apply-target-profile.py ${ROOT}"],
    }
    (MODULES / "linuxiso_apply_target_profile.conf").write_text(
        yaml.safe_dump(apply_target_profile, sort_keys=False),
        encoding="utf-8",
    )
    target_finalize = {
        "dontChroot": False,
        "timeout": 120,
        "verbose": True,
        "script": ["/usr/lib/linux-iso/finalize-target"],
    }
    (MODULES / "linuxiso_target_finalize.conf").write_text(
        yaml.safe_dump(target_finalize, sort_keys=False),
        encoding="utf-8",
    )
    patch_text_configs(source, kernel)
    patch_branding_text()
    patch_settings()

    stale = []
    for base in (Path("/etc/calamares"), Path("/usr/share/calamares")):
        if not base.is_dir():
            continue
        for path in base.rglob("*.conf"):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "/cdrom/casper/vmlinuz" in text:
                stale.append(str(path))
    if stale:
        raise SystemExit("stale Casper kernel path remains: " + ", ".join(stale))

    settings = yaml.safe_load(SETTINGS.read_text(encoding="utf-8")) or {}
    risky = []
    for phase in settings.get("sequence", []):
        if not isinstance(phase, dict):
            continue
        for item in phase.get("show", []):
            if isinstance(item, str) and (item == "pkgselect" or item.startswith("pkgselect@")):
                risky.append(item)
        for item in phase.get("exec", []):
            if not isinstance(item, str):
                continue
            if (
                item == "packages"
                or item.startswith("packages@")
                or item == "shellprocess@before_bootloader_kerncopy"
                or item == "initramfs"
                or item.startswith("initramfs@")
                or item == "contextualprocess@before_bootloader"
                or item == "shellprocess@add386arch"
                or item == "shellprocess@rmcdrom"
                or item == "shellprocess@logs"
                or item == "pkgselectprocess"
                or item.startswith("pkgselectprocess@")
                or item.startswith("contextualprocess@pkgselect")
            ):
                risky.append(item)
    if risky:
        raise SystemExit("unsafe Ubuntu live-ISO Calamares jobs remain: " + ", ".join(risky))

    exec_jobs = [
        item
        for phase in settings.get("sequence", [])
        if isinstance(phase, dict)
        for item in phase.get("exec", [])
        if isinstance(item, str)
    ]
    profile_job = "shellprocess@linuxiso_apply_target_profile"
    if profile_job not in exec_jobs:
        raise SystemExit("Linux ISO target-profile job is missing from Calamares exec sequence")
    if "linuxiso-install" not in exec_jobs:
        raise SystemExit("Linux ISO application/install job is missing from Calamares exec sequence")
    if exec_jobs.index(profile_job) > exec_jobs.index("linuxiso-install"):
        raise SystemExit("Linux ISO target-profile job must run before linuxiso-install")
    selection_jobs = [
        item for item in exec_jobs if item.startswith("netinstall@linuxiso_")
    ]
    if selection_jobs and max(exec_jobs.index(item) for item in selection_jobs) > exec_jobs.index("linuxiso-install"):
        raise SystemExit("Linux ISO application selection jobs must run before linuxiso-install")


if __name__ == "__main__":
    main()
'''


LIVE_PROFILE_SCRIPT = r'''#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
from pathlib import Path

PAYLOAD = Path("/usr/share/linux-iso/profile/payload/home")
TARGET = Path("/home/live")
PERSONALIZATION_PATHS = (
    "Desktop",
    ".config/kdeglobals",
    ".config/kwinrc",
    ".config/plasmashellrc",
    ".config/plasmarc",
    ".config/plasma-org.kde.plasma.desktop-appletsrc",
    ".config/kglobalshortcutsrc",
    ".config/kwinrulesrc",
    ".config/kcminputrc",
    ".config/kscreenlockerrc",
    ".config/ksplashrc",
    ".config/krunnerrc",
    ".config/plasma-localerc",
    ".config/powermanagementprofilesrc",
    ".config/powerdevilrc",
    ".config/systemsettingsrc",
    ".config/kded6rc",
    ".config/klaunchrc",
    ".config/kactivitymanagerd-statsrc",
    ".config/breezerc",
    ".config/dolphinrc",
    ".config/konsolerc",
    ".config/mimeapps.list",
    ".config/gtk-3.0",
    ".config/gtk-4.0",
    ".config/qt5ct",
    ".config/qt6ct",
    ".config/Kvantum",
    ".local/share/plasma",
    ".local/share/aurorae",
    ".local/share/kwin",
    ".local/share/color-schemes",
    ".local/share/icons",
    ".icons",
    ".local/share/themes",
    ".themes",
    ".local/share/fonts",
    ".fonts",
    ".local/share/konsole",
    ".local/share/applications",
    ".local/share/kactivitymanagerd",
    ".face",
    ".face.icon",
)


def ids():
    for line in Path("/etc/passwd").read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split(":")
        if len(fields) >= 4 and fields[0] == "live":
            return int(fields[2]), int(fields[3])
    raise RuntimeError("live user is missing")


def clear_vendor_personalization():
    for relative in PERSONALIZATION_PATHS:
        path = TARGET / relative
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def main():
    if not PAYLOAD.is_dir():
        raise SystemExit("Linux ISO profile payload is missing")
    TARGET.mkdir(parents=True, exist_ok=True)
    uid, gid = ids()
    clear_vendor_personalization()
    copied = 0
    for src in PAYLOAD.rglob("*"):
        rel = src.relative_to(PAYLOAD)
        dst = TARGET / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            os.chown(dst, uid, gid)
            continue
        if not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = src.read_bytes()
            text = None if b"\x00" in raw else raw.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            text = None
        if text is None:
            shutil.copy2(src, dst)
        else:
            dst.write_text(text.replace("{{HOME}}", "/home/live"), encoding="utf-8")
            shutil.copymode(src, dst)
        os.chown(dst, uid, gid)
        copied += 1
    os.chown(TARGET, uid, gid)
    marker = TARGET / ".local/state/linux-iso/profile-applied"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"files={copied}\n", encoding="utf-8")
    os.chown(marker.parent.parent, uid, gid)
    os.chown(marker.parent, uid, gid)
    os.chown(marker, uid, gid)


if __name__ == "__main__":
    main()
'''


TARGET_PROFILE_SCRIPT = r"""#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

PAYLOAD = Path("/usr/share/linux-iso/profile/payload/home")
PERSONALIZATION_PATHS = (
    "Desktop",
    ".config/kdeglobals",
    ".config/kwinrc",
    ".config/plasmashellrc",
    ".config/plasmarc",
    ".config/plasma-org.kde.plasma.desktop-appletsrc",
    ".config/kglobalshortcutsrc",
    ".config/kwinrulesrc",
    ".config/kcminputrc",
    ".config/kscreenlockerrc",
    ".config/ksplashrc",
    ".config/krunnerrc",
    ".config/plasma-localerc",
    ".config/powermanagementprofilesrc",
    ".config/powerdevilrc",
    ".config/systemsettingsrc",
    ".config/kded6rc",
    ".config/klaunchrc",
    ".config/kactivitymanagerd-statsrc",
    ".config/breezerc",
    ".config/dolphinrc",
    ".config/konsolerc",
    ".config/mimeapps.list",
    ".config/gtk-3.0",
    ".config/gtk-4.0",
    ".config/qt5ct",
    ".config/qt6ct",
    ".config/Kvantum",
    ".local/share/plasma",
    ".local/share/aurorae",
    ".local/share/kwin",
    ".local/share/color-schemes",
    ".local/share/icons",
    ".icons",
    ".local/share/themes",
    ".themes",
    ".local/share/fonts",
    ".fonts",
    ".local/share/konsole",
    ".local/share/applications",
    ".local/share/kactivitymanagerd",
    ".face",
    ".face.icon",
)


def target_user(root: Path) -> tuple[str, int, int, Path]:
    passwd = root / "etc/passwd"
    if not passwd.is_file():
        raise RuntimeError("target /etc/passwd is missing")
    candidates = []
    for line in passwd.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split(":")
        if len(fields) < 7:
            continue
        name, uid_raw, gid_raw, home_raw = fields[0], fields[2], fields[3], fields[5]
        try:
            uid, gid = int(uid_raw), int(gid_raw)
        except ValueError:
            continue
        if name in {"live", "nobody"} or not (1000 <= uid < 65534):
            continue
        if not home_raw.startswith("/home/"):
            continue
        home = root / home_raw.lstrip("/")
        candidates.append((uid, name, gid, home))
    if not candidates:
        raise RuntimeError("could not identify the Calamares-created target user")
    uid, name, gid, home = sorted(candidates)[0]
    return name, uid, gid, home


def clear_vendor_personalization(home: Path) -> None:
    for relative in PERSONALIZATION_PATHS:
        path = home / relative
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def normalize_local(value: str) -> str | None:
    value = unquote(value.strip())
    if value.startswith("file://"):
        parsed = urlparse(value)
        if parsed.scheme != "file":
            return None
        return unquote(parsed.path)
    if value.startswith("/"):
        return value
    return None


def validate_wallpaper(home: Path) -> int:
    config = home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not config.is_file():
        raise RuntimeError("restored Plasma desktop configuration is missing")
    checked = 0
    text = config.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() not in {"Image", "SlidePaths"}:
            continue
        values = [value] if key.strip() == "Image" else value.replace(";", ",").split(",")
        for raw in values:
            local = normalize_local(raw)
            if not local or not local.startswith(str(home) + "/"):
                continue
            checked += 1
            if not Path(local).exists():
                raise RuntimeError(f"restored wallpaper asset is missing: {local}")
    return checked


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-target-profile ROOT")
    root = Path(sys.argv[1]).resolve()
    if not PAYLOAD.is_dir():
        raise RuntimeError("Linux ISO profile payload is missing in live media")
    username, uid, gid, home = target_user(root)
    home.mkdir(parents=True, exist_ok=True)
    clear_vendor_personalization(home)

    copied = 0
    for src in PAYLOAD.rglob("*"):
        rel = src.relative_to(PAYLOAD)
        dst = home / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            os.chown(dst, uid, gid)
            continue
        if not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = src.read_bytes()
            text = None if b"\x00" in raw else raw.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            text = None
        if text is None:
            shutil.copy2(src, dst)
        else:
            dst.write_text(text.replace("{{HOME}}", str(home)), encoding="utf-8")
            shutil.copymode(src, dst)
        os.chown(dst, uid, gid)
        copied += 1

    os.chown(home, uid, gid)
    wallpaper_checks = validate_wallpaper(home)
    state = root / "var/lib/linux-iso"
    state.mkdir(parents=True, exist_ok=True)
    (state / "target-username").write_text(username + "\n", encoding="utf-8")
    (state / "profile-applied").write_text(
        f"user={username}\nfiles={copied}\nwallpaper_refs={wallpaper_checks}\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


def _read_manifest(profile: Path) -> dict[str, Any]:
    path = profile / "manifest.yaml"
    if not path.is_file():
        raise BuilderError(f"Missing profile manifest: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _validate_recipe_compatibility(manifest: dict[str, Any], recipe: BaseRecipe) -> None:
    native_providers = {
        p.get("provider")
        for p in manifest.get("packages", [])
        if p.get("provider") in {"apt", "pacman", "dnf", "zypper"}
    }
    incompatible = sorted(p for p in native_providers if p != recipe.native_provider)
    if incompatible:
        raise BuilderError(
            f"Recipe {recipe.id} uses {recipe.native_provider}, but the profile contains "
            f"native packages from: {', '.join(incompatible)}. "
            "Cross-family package translation is not implemented yet."
        )


def _required_base_packages(manifest: dict[str, Any]) -> list[str]:
    return sorted(
        {
            p["name"]
            for p in manifest.get("packages", [])
            if p.get("provider") == "apt" and p.get("required_for_appearance")
        }
    )


def _optional_provider_support(manifest: dict[str, Any]) -> list[str]:
    providers = {p.get("provider") for p in manifest.get("packages", [])}
    packages: list[str] = []
    if "flatpak" in providers:
        packages.append("flatpak")
    if "snap" in providers:
        packages.append("snapd")
    return packages


def _indent_xml(root: ET.Element) -> None:
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        pass


def _write_config_xml(destination: Path, recipe: BaseRecipe, manifest: dict[str, Any]) -> None:
    source = manifest.get("source", {}) or {}
    source_name = str(source.get("distro_name_short") or source.get("distro_name") or "Linux").strip()
    source_name = re.sub(r"\s+GNU/Linux.*$", "", source_name, flags=re.IGNORECASE).strip() or "Linux"
    root = ET.Element("image", {"schemaversion": "8.5", "name": recipe.image_name})
    description = ET.SubElement(root, "description", {"type": "system"})
    ET.SubElement(description, "author").text = "Linux ISO project"
    ET.SubElement(description, "contact").text = "local-build"
    ET.SubElement(description, "specification").text = f"{PRODUCT_NAME} personalized KDE Plasma live image"

    preferences = ET.SubElement(root, "preferences")
    ET.SubElement(preferences, "version").text = __version__
    ET.SubElement(preferences, "packagemanager").text = "apt"
    ET.SubElement(preferences, "locale").text = "en_US"
    ET.SubElement(preferences, "timezone").text = "UTC"
    image_type = ET.SubElement(
        preferences,
        "type",
        {
            "image": "iso",
            "primary": "true",
            "flags": "overlay",
            "filesystem": "squashfs",
            "firmware": "efi",
            "gpt_hybrid_mbr": "true",
        },
    )
    ET.SubElement(
        image_type,
        "bootloader",
        {"name": "grub2", "grub_template": "grub-live-safe.cfg.tmpl"},
    )

    users = ET.SubElement(root, "users")
    ET.SubElement(
        users,
        "user",
        {
            "name": "live",
            "password": "live",
            "pwdformat": "plain",
            "home": "/home/live",
            "groups": "users,sudo,audio,video,plugdev,netdev",
            "realname": f"{source_name} Live",
            "shell": "/bin/bash",
        },
    )

    for repo in recipe.repositories:
        node = ET.SubElement(
            root,
            "repository",
            {
                "type": "apt-deb",
                "alias": repo.alias,
                "imageinclude": "true",
                "components": repo.components,
                "distribution": repo.distribution,
            },
        )
        source = ET.SubElement(node, "source", {"path": repo.url})
        if repo.signing_key:
            ET.SubElement(source, "signing", {"key": repo.signing_key})

    bootstrap = ET.SubElement(root, "packages", {"type": "bootstrap"})
    for name in recipe.bootstrap_packages:
        ET.SubElement(bootstrap, "package", {"name": name})

    image = ET.SubElement(root, "packages", {"type": "image"})
    packages = set(recipe.image_packages)
    packages.update(_required_base_packages(manifest))
    packages.update(_optional_provider_support(manifest))
    for name in sorted(packages):
        ET.SubElement(image, "package", {"name": name})

    _indent_xml(root)
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def _write_build_scripts(destination: Path, recipe: BaseRecipe, manifest: dict[str, Any]) -> None:
    source = manifest.get("source", {}) or {}
    source_name = str(source.get("distro_name_short") or source.get("distro_name") or "Linux").strip()
    source_name = re.sub(r"\s+GNU/Linux.*$", "", source_name, flags=re.IGNORECASE).strip() or "Linux"
    installer_name = f"Install {source_name}"
    installer_comment = f"Install the captured {source_name} desktop profile"
    installer_name_tr = f"{source_name}'u Kur" if not source_name.endswith(("a", "e")) else f"{source_name}'yı Kur"
    patcher = destination / "root/usr/lib/linux-iso/patch-calamares.py"
    patcher.parent.mkdir(parents=True, exist_ok=True)
    patcher.write_text(PATCH_CALAMARES, encoding="utf-8")
    patcher.chmod(0o755)

    runtime_patcher = destination / "root/usr/lib/linux-iso/patch-calamares-runtime.py"
    runtime_patcher.write_text(RUNTIME_CALAMARES_PATCH, encoding="utf-8")
    runtime_patcher.chmod(0o755)

    live_profile = destination / "root/usr/lib/linux-iso/apply-live-profile.py"
    live_profile.write_text(LIVE_PROFILE_SCRIPT, encoding="utf-8")
    live_profile.chmod(0o755)

    target_profile = destination / "root/usr/lib/linux-iso/apply-target-profile.py"
    target_profile.write_text(TARGET_PROFILE_SCRIPT, encoding="utf-8")
    target_profile.chmod(0o755)

    media_helper = destination / "root/usr/lib/linux-iso/prepare-calamares-media"
    media_helper.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "mkdir -p /cdrom\n"
        "if ! mountpoint -q /cdrom; then\n"
        "  if [ -e /dev/disk/by-label/CDROM ]; then\n"
        "    mount -o ro /dev/disk/by-label/CDROM /cdrom || true\n"
        "  fi\n"
        "fi\n"
        "SOURCE=\"\"\n"
        "for candidate in /cdrom/LiveOS/squashfs.img /run/initramfs/live/LiveOS/squashfs.img /run/initramfs/LiveOS/squashfs.img; do\n"
        "  if [ -f \"$candidate\" ]; then SOURCE=\"$candidate\"; break; fi\n"
        "done\n"
        "if [ -z \"$SOURCE\" ]; then\n"
        "  SOURCE=$(find /run /cdrom -maxdepth 6 -type f -path '*/LiveOS/squashfs.img' -print -quit 2>/dev/null || true)\n"
        "fi\n"
        "if [ -z \"$SOURCE\" ] || [ ! -f \"$SOURCE\" ]; then\n"
        "  echo 'Linux ISO - Suret: could not locate KIWI LiveOS/squashfs.img' >&2\n"
        "  exit 10\n"
        "fi\n"
        "KERNEL_SOURCE=\"\"\n"
        "for candidate in /cdrom/boot/x86_64/loader/linux /run/initramfs/live/boot/x86_64/loader/linux /run/initramfs/boot/x86_64/loader/linux; do\n"
        "  if [ -f \"$candidate\" ]; then KERNEL_SOURCE=\"$candidate\"; break; fi\n"
        "done\n"
        "if [ -z \"$KERNEL_SOURCE\" ]; then\n"
        "  KERNEL_SOURCE=$(find /run /cdrom -maxdepth 7 -type f -path '*/boot/x86_64/loader/linux' -print -quit 2>/dev/null || true)\n"
        "fi\n"
        "if [ -z \"$KERNEL_SOURCE\" ] || [ ! -f \"$KERNEL_SOURCE\" ]; then\n"
        "  echo 'Linux ISO - Suret: could not locate KIWI live kernel' >&2\n"
        "  exit 11\n"
        "fi\n"
        "cat > /etc/calamares/modules/unpackfs.conf <<EOF\n"
        "---\n"
        "unpack:\n"
        "  - source: \"$SOURCE\"\n"
        "    sourcefs: \"squashfs\"\n"
        "    destination: \"\"\n"
        "EOF\n"
        "cat > /etc/calamares/modules/before_bootloader_mkdirs_context.conf <<EOF\n"
        "---\n"
        "dontChroot: true\n"
        "timeout: 30\n"
        "script:\n"
        "  - \"mkdir -pv \\${ROOT}/boot\"\n"
        "  - \"test -e \\${ROOT}/boot/vmlinuz-\\$(uname -r) || cp $KERNEL_SOURCE \\${ROOT}/boot/vmlinuz-\\$(uname -r)\"\n"
        "EOF\n"
        "cat > /etc/calamares/modules/before_bootloader_context.conf <<'EOF'\n"
        "---\n"
        "firmwareType:\n"
        "  \"*\": \"-/bin/true\"\n"
        "EOF\n"
        "python3 /usr/lib/linux-iso/patch-calamares-runtime.py \"$SOURCE\" \"$KERNEL_SOURCE\"\n"
        "printf '%s\\n' \"Linux ISO - Suret Calamares source: $SOURCE\"\n"
        "printf '%s\\n' \"Linux ISO - Suret kernel source: $KERNEL_SOURCE\"\n",
        encoding="utf-8",
    )
    media_helper.chmod(0o755)

    target_initramfs = destination / "root/usr/lib/linux-iso/update-target-initramfs"
    target_initramfs.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "if ! command -v update-initramfs >/dev/null 2>&1; then\n"
        "  echo 'Linux ISO - Suret: update-initramfs is missing in target system' >&2\n"
        "  exit 12\n"
        "fi\n"
        "found=0\n"
        "for modules_dir in /lib/modules/*; do\n"
        "  [ -d \"$modules_dir\" ] || continue\n"
        "  version=${modules_dir##*/}\n"
        "  found=1\n"
        "  if [ -e \"/boot/initrd.img-$version\" ]; then\n"
        "    update-initramfs -u -k \"$version\"\n"
        "  else\n"
        "    update-initramfs -c -k \"$version\"\n"
        "  fi\n"
        "done\n"
        "if [ \"$found\" -eq 0 ]; then\n"
        "  echo 'Linux ISO - Suret: no target kernel modules found for initramfs generation' >&2\n"
        "  exit 13\n"
        "fi\n",
        encoding="utf-8",
    )
    target_initramfs.chmod(0o755)

    target_finalize = destination / "root/usr/lib/linux-iso/finalize-target"
    target_finalize.write_text(
        "#!/bin/sh\n"
        "set -u\n"
        "marker=/var/lib/linux-iso/target-username\n"
        "target_user=''\n"
        "if [ -r \"$marker\" ]; then IFS= read -r target_user < \"$marker\" || true; fi\n"
        "rm -f /etc/sddm.conf.d/99-linux-iso-live.conf\n"
        "rm -f /etc/sudoers.d/99-linux-iso-live\n"
        "rm -f /etc/apt/sources.list.d/cdrom.sources /etc/apt/sources.list.d/cdrom.list\n"
        "rm -f /usr/bin/linux-iso-installer\n"
        "rm -f /usr/local/share/applications/linux-iso-installer.desktop\n"
        "find /usr/share/applications -maxdepth 1 -type f -iname '*calamares*.desktop' -delete 2>/dev/null || true\n"
        "if [ \"$target_user\" != live ] && getent passwd live >/dev/null 2>&1; then\n"
        "  if command -v userdel >/dev/null 2>&1; then userdel -r live >/dev/null 2>&1 || true; fi\n"
        "  if getent passwd live >/dev/null 2>&1; then\n"
        "    if command -v passwd >/dev/null 2>&1; then passwd -l live >/dev/null 2>&1 || true; fi\n"
        "    rm -rf /home/live\n"
        "  fi\n"
        "fi\n"
        "rm -f \"$marker\"\n"
        "rm -f /usr/lib/linux-iso/prepare-calamares-media\n"
        "rm -f /usr/lib/linux-iso/patch-calamares.py /usr/lib/linux-iso/patch-calamares-runtime.py\n"
        "rm -f /usr/lib/linux-iso/update-target-initramfs /usr/lib/linux-iso/finalize-target\n"
        "rm -f /usr/lib/linux-iso/apply-target-profile.py /usr/lib/linux-iso/apply-live-profile.py\n"
        "rm -f /usr/lib/linux-iso/hide-foreign-installers\n"
        "exit 0\n",
        encoding="utf-8",
    )
    target_finalize.chmod(0o755)

    installer = destination / "root/usr/bin/linux-iso-installer"
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "sudo /usr/lib/linux-iso/prepare-calamares-media\n"
        "exec sudo -E /usr/bin/calamares -D8\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)

    hide_foreign_installers = destination / "root/usr/lib/linux-iso/hide-foreign-installers"
    hide_foreign_installers.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import re\n"
        "\n"
        "source_name = " + repr(source_name.lower()) + "\n"
        "mask_dir = Path('/usr/local/share/applications')\n"
        "mask_dir.mkdir(parents=True, exist_ok=True)\n"
        "patterns = (\n"
        "    'install kubuntu', 'kubuntu installer', 'kubuntu-installer',\n"
        "    'kubuntu-installer-prompt', 'ubiquity', 'oem mode',\n"
        ")\n"
        "for desktop in Path('/usr/share/applications').glob('*.desktop'):\n"
        "    if desktop.name == 'linux-iso-installer.desktop':\n"
        "        continue\n"
        "    try:\n"
        "        text = desktop.read_text(encoding='utf-8', errors='replace')\n"
        "    except OSError:\n"
        "        continue\n"
        "    haystack = (desktop.name + '\\n' + text).lower()\n"
        "    if not any(pattern in haystack for pattern in patterns):\n"
        "        continue\n"
        "    # Never hide a launcher that explicitly belongs to the captured\n"
        "    # source distribution.  The filter is intended only for the\n"
        "    # Ubuntu/Kubuntu construction substrate.\n"
        "    if source_name and source_name in haystack and 'kubuntu' not in haystack:\n"
        "        continue\n"
        "    target = mask_dir / desktop.name\n"
        "    target.write_text('[Desktop Entry]\\nType=Application\\nHidden=true\\nNoDisplay=true\\nX-LinuxISO-Masked=true\\n', encoding='utf-8')\n"
        "\n"
        "# Also mask Kubuntu OEM prompt entries that may use unexpected names.\n"
        "for desktop in Path('/usr/share/applications').glob('*oem*.desktop'):\n"
        "    try:\n"
        "        text = desktop.read_text(encoding='utf-8', errors='replace').lower()\n"
        "    except OSError:\n"
        "        continue\n"
        "    if 'kubuntu' in text or 'installer' in text:\n"
        "        (mask_dir / desktop.name).write_text('[Desktop Entry]\\nType=Application\\nHidden=true\\nNoDisplay=true\\nX-LinuxISO-Masked=true\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    hide_foreign_installers.chmod(0o755)

    grub_template = destination / "grub-live-safe.cfg.tmpl"
    grub_template.write_text(
        "# Linux ISO - Suret BIOS-safe live boot template\n"
        "search ${search_params}\n"
        "set default=${default_boot}\n"
        "set timeout=${boot_timeout}\n"
        "set timeout_style=${boot_timeout_style}\n"
        "if [ -n \"$${iso_path}\" ]; then\n"
        "  isoboot=\"iso-scan/filename=$${iso_path}\"\n"
        "fi\n"
        "terminal_input ${terminal_input}\n"
        "terminal_output ${terminal_output}\n"
        "\n"
        "menuentry \"${title}\" --class os --unrestricted {\n"
        "  echo Loading kernel...\n"
        "  if [ \"$${grub_platform}\" = \"pc\" ]; then\n"
        "    insmod linux16\n"
        "    linux16 ($$root)${bootpath}/${kernel_file} $${isoboot} ${boot_options}\n"
        "    echo Loading initrd...\n"
        "    initrd16 ($$root)${bootpath}/${initrd_file}\n"
        "  else\n"
        "    linux ($$root)${bootpath}/${kernel_file} $${isoboot} ${boot_options}\n"
        "    echo Loading initrd...\n"
        "    initrd ($$root)${bootpath}/${initrd_file}\n"
        "  fi\n"
        "}\n"
        "\n"
        "menuentry \"Boot from Hard Disk\" --class os --unrestricted {\n"
        "  exit\n"
        "}\n",
        encoding="utf-8",
    )

    config_sh = destination / "config.sh"
    config_sh.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        "test -f /.kconfig && . /.kconfig\n"
        "python3 /usr/lib/linux-iso/patch-calamares.py\n"
        "python3 /usr/lib/linux-iso/apply-live-profile.py\n"
        "python3 /usr/lib/linux-iso/hide-foreign-installers\n"
        "install -d -m 0755 /etc/sddm.conf.d\n"
        "cat > /etc/sddm.conf.d/99-linux-iso-live.conf <<'EOF'\n"
        "[General]\n"
        "DisplayServer=x11\n"
        "\n"
        "[Autologin]\n"
        "User=live\n"
        "Session=plasmax11\n"
        "Relogin=true\n"
        "EOF\n"
        "install -d -m 0755 /etc/sudoers.d\n"
        "echo 'live ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/99-linux-iso-live\n"
        "chmod 0440 /etc/sudoers.d/99-linux-iso-live\n"
        "printf 'localhost.localdomain\n' > /etc/hostname\n"
        "grep -qE '^[[:space:]]*127[.]0[.]1[.]1[[:space:]]+localhost[.]localdomain' /etc/hosts || printf '127.0.1.1 localhost.localdomain localhost\n' >> /etc/hosts\n"
        "install -d -o live -g users -m 0755 /home/live/.local/bin\n"
        "touch /home/live/.local/bin/env\n"
        "chown live:users /home/live/.local/bin/env\n"
        "install -d -o live -g users -m 0755 /home/live/Desktop\n"
        "install -d -o live -g users -m 0755 /home/live/.config\n"
        "cat > /home/live/.config/kscreenlockerrc <<'EOF'\n"
        "[Daemon]\n"
        "Autolock=false\n"
        "LockOnResume=false\n"
        "Timeout=0\n"
        "EOF\n"
        "install -d -m 0755 /usr/local/share/applications\n"
        "cat > /usr/local/share/applications/linux-iso-installer.desktop <<'EOF'\n"
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={installer_name}\n"
        f"Name[tr]={installer_name_tr}\n"
        f"Comment={installer_comment}\n"
        f"Comment[tr]={source_name} kurulumunu baslat\n"
        "Exec=linux-iso-installer\n"
        "Icon=system-software-install\n"
        "Terminal=false\n"
        "Categories=System;\n"
        "EOF\n"
        "chmod 0755 /usr/local/share/applications/linux-iso-installer.desktop\n"
        "cp /usr/local/share/applications/linux-iso-installer.desktop /home/live/Desktop/linux-iso-installer.desktop\n"
        "chmod 0755 /home/live/Desktop/linux-iso-installer.desktop\n"
        "chown -R live:users /home/live\n"
        "command -v baseSetRunlevel >/dev/null 2>&1 && baseSetRunlevel 5 || true\n"
        "command -v baseService >/dev/null 2>&1 && baseService sddm on || true\n"
        "command -v baseService >/dev/null 2>&1 && baseService NetworkManager on || true\n",
        encoding="utf-8",
    )
    config_sh.chmod(0o755)

    build_sh = destination / "build.sh"
    build_sh.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        "HERE=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "OUT=${1:-${LINUX_ISO_RESULT_DIR:-${HERE}-result}}\n"
        "BACKEND=${LINUX_ISO_BUILD_BACKEND:-auto}\n"
        f"BOX=${{LINUX_ISO_BOX:-{recipe.preferred_box}}}\n"
        "KIWI_VERSION=${LINUX_ISO_KIWI_VERSION:-11.1.16}\n"
        "NICE_LEVEL=${LINUX_ISO_NICE_LEVEL:-10}\n"
        "IO_NICE_LEVEL=${LINUX_ISO_IO_NICE_LEVEL:-7}\n"
        "case \"$OUT/\" in \"$HERE/\"*) echo \"Refusing nested KIWI target dir: $OUT (description: $HERE)\" >&2; echo \"Use a sibling result directory, for example: ${HERE}-result\" >&2; exit 2;; esac\n"
        "mkdir -p \"$OUT\"\n"
        "if [ \"${LINUX_ISO_INHIBITED:-0}\" != 1 ] && [ \"${LINUX_ISO_KEEP_AWAKE:-1}\" = 1 ] && command -v systemd-inhibit >/dev/null 2>&1; then\n"
        "  exec systemd-inhibit --what=sleep --mode=block --why='Linux ISO - Suret build' env LINUX_ISO_INHIBITED=1 \"$0\" \"$@\"\n"
        "fi\n"
        "BUILD_LOG=${LINUX_ISO_BUILD_LOG:-$OUT/build-session.log}\n"
        "RESOURCE_LOG=${LINUX_ISO_RESOURCE_LOG:-$OUT/resource-monitor.log}\n"
        "exec > >(tee -a \"$BUILD_LOG\") 2>&1\n"
        "echo \"[$(date -Is)] Linux ISO - Suret build starting\"\n"
        "echo \"Build log: $BUILD_LOG\"\n"
        "echo \"Resource log: $RESOURCE_LOG\"\n"
        "echo 'Validating KIWI description before starting the build box...'\n"
        "uv tool run --from \"kiwi==$KIWI_VERSION\" kiwi-ng --logfile stdout image info --description \"$HERE\" > \"$OUT/kiwi-preflight.log\" 2>&1 || { cat \"$OUT/kiwi-preflight.log\" >&2; echo 'KIWI description preflight failed.' >&2; exit 7; }\n"
        "cat \"$OUT/kiwi-preflight.log\"\n"
        "if [ \"${LINUX_ISO_MONITOR_RESOURCES:-1}\" = 1 ]; then\n"
        "  (while true; do { echo \"[$(date -Is)]\"; grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo || true; cat /proc/loadavg || true; df -h \"$OUT\" | tail -n 1 || true; echo; } >> \"$RESOURCE_LOG\"; sleep 60; done) &\n"
        "  MONITOR_PID=$!\n"
        "  trap 'kill \"$MONITOR_PID\" 2>/dev/null || true' EXIT INT TERM\n"
        "fi\n"
        "if [ \"$BACKEND\" = auto ]; then\n"
        "  if command -v uv >/dev/null 2>&1 && command -v podman >/dev/null 2>&1; then BACKEND=container;\n"
        "  elif command -v kiwi-boxbuild >/dev/null 2>&1 && command -v podman >/dev/null 2>&1; then BACKEND=boxbuild;\n"
        "  elif command -v kiwi-ng >/dev/null 2>&1 && command -v podman >/dev/null 2>&1 && { command -v qemu-system-x86_64 >/dev/null 2>&1 || command -v qemu-kvm >/dev/null 2>&1; }; then BACKEND=boxbuild;\n"
        "  elif command -v kiwi-ng >/dev/null 2>&1; then BACKEND=direct;\n"
        "  else echo 'No KIWI backend found. Run: linux-iso build-doctor' >&2; exit 2; fi\n"
        "fi\n"
        "echo \"Linux ISO - Suret build backend: $BACKEND\"\n"
        "echo \"Build box: $BOX\"\n"
        "if [ \"$BACKEND\" = container ]; then\n"
        "  command -v uv >/dev/null 2>&1 || { echo 'uv is required for container backend' >&2; exit 2; }\n"
        "  command -v podman >/dev/null 2>&1 || { echo 'podman is required for container backend' >&2; exit 2; }\n"
        "  BOX_IMAGE=${LINUX_ISO_BOX_IMAGE:-registry.opensuse.org/virtualization/appliances/selfcontained/${BOX}/images/${BOX}:latest}\n"
        "  echo \"Using direct KIWI container backend: $BOX_IMAGE\"\n"
        "  echo 'This bypasses kiwi.service/systemd inside the box and runs kiwi-ng system build directly.'\n"
        "  sudo mkdir -p /var/cache/kiwi\n"
        "  sudo podman pull \"$BOX_IMAGE\"\n"
        "  echo 'Checking kiwi-ng inside the build container...'\n"
        "  sudo podman run --rm --entrypoint /usr/bin/kiwi-ng \"$BOX_IMAGE\" --version\n"
        "  RC=0\n"
        "  PODMAN_ARGS=(run --rm --privileged --net host --security-opt label=disable --cap-add AUDIT_WRITE --cap-add AUDIT_CONTROL --cap-add CAP_MKNOD --cap-add CAP_SYS_ADMIN --volume /var/cache/kiwi:/var/cache/kiwi --volume \"$HERE:/description:ro\" --volume \"$OUT:/result\" --volume /dev:/dev --entrypoint /usr/bin/kiwi-ng \"$BOX_IMAGE\" --debug --logfile stdout system build --description /description --target-dir /result)\n"
        "  if command -v ionice >/dev/null 2>&1; then\n"
        "    nice -n \"$NICE_LEVEL\" ionice -c 2 -n \"$IO_NICE_LEVEL\" sudo podman \"${PODMAN_ARGS[@]}\" || RC=$?\n"
        "  else\n"
        "    nice -n \"$NICE_LEVEL\" sudo podman \"${PODMAN_ARGS[@]}\" || RC=$?\n"
        "  fi\n"
        "  sudo chown -R \"$(id -u):$(id -g)\" \"$OUT\" 2>/dev/null || true\n"
        "elif [ \"$BACKEND\" = boxbuild ]; then\n"
        "  echo 'VM boxbuild fallback selected; first use downloads a large QCOW2 build box.'\n"
        "  RC=0\n"
        "  if command -v kiwi-boxbuild >/dev/null 2>&1; then kiwi-boxbuild --box \"$BOX\" kiwi --description \"$HERE\" --target-dir \"$OUT\" || RC=$?;\n"
        "  elif command -v kiwi-ng >/dev/null 2>&1; then kiwi-ng --debug system boxbuild --box \"$BOX\" kiwi --description \"$HERE\" --target-dir \"$OUT\" || RC=$?;\n"
        "  else echo 'boxbuild backend requested but neither kiwi-boxbuild nor kiwi-ng is available' >&2; exit 2; fi\n"
        "elif [ \"$BACKEND\" = direct ]; then\n"
        "  RC=0\n"
        "  kiwi-ng image info --description \"$HERE\" --resolve-package-list > \"$OUT/package-resolution.txt\" || RC=$?\n"
        "  if [ \"$RC\" -eq 0 ]; then KIWI=$(command -v kiwi-ng); sudo \"$KIWI\" --debug system build --description \"$HERE\" --target-dir \"$OUT\" || RC=$?; fi\n"
        "else\n"
        "  echo \"Unknown backend: $BACKEND\" >&2; exit 2\n"
        "fi\n"
        "if [ \"$RC\" -ne 0 ]; then echo \"KIWI backend failed with exit code $RC\" >&2; exit \"$RC\"; fi\n"
        "ISO=$(find \"$OUT\" -maxdepth 3 -type f -name '*.iso' -print | sort | tail -n 1)\n"
        "if [ -z \"${ISO:-}\" ]; then\n"
        "  echo 'ERROR: KIWI backend exited successfully but no ISO artifact was created.' >&2\n"
        "  echo \"Result directory: $OUT\" >&2\n"
        "  find \"$OUT\" -maxdepth 3 -type f -printf '  %p  %s bytes\n' 2>/dev/null | sort >&2 || true\n"
        "  if [ -s \"$OUT/build/image-root.log\" ]; then echo '--- KIWI image-root.log tail ---' >&2; tail -n 120 \"$OUT/build/image-root.log\" >&2; fi\n"
        "  exit 6\n"
        "fi\n"
        "echo \"ISO artifact: $ISO\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    build_sh.chmod(0o755)

    qemu_sh = destination / "test-qemu.sh"
    qemu_sh.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        "HERE=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "RESULT=${1:-${LINUX_ISO_RESULT_DIR:-${HERE}-result}}\n"
        "MODE=${2:-${LINUX_ISO_QEMU_MODE:-live}}\n"
        "ISO=''\n"
        "if [ \"$MODE\" = live ]; then ISO=$(find \"$RESULT\" -maxdepth 2 -type f -name '*.iso' -print | sort | tail -n 1); fi\n"
        "if [ \"$MODE\" = live ] && [ -z \"${ISO:-}\" ]; then echo \"No ISO found under $RESULT\" >&2; exit 2; fi\n"
        "if [ \"$MODE\" != live ] && [ \"$MODE\" != installed ]; then echo 'Mode must be live or installed' >&2; exit 2; fi\n"
        "QEMU=$(command -v qemu-system-x86_64 || command -v qemu-kvm || true)\n"
        "if [ -z \"$QEMU\" ]; then echo 'qemu-system-x86_64 not found' >&2; exit 2; fi\n"
        "ACCEL=(-accel tcg,thread=single -cpu max,la57=off)\n"
        "if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then ACCEL=(-enable-kvm -cpu host); fi\n"
        "FIRMWARE=${LINUX_ISO_QEMU_FIRMWARE:-uefi}\n"
        "DISK=${LINUX_ISO_QEMU_DISK:-$RESULT/linux-iso-suret-test.qcow2}\n"
        "DISK_SIZE=${LINUX_ISO_QEMU_DISK_SIZE:-40G}\n"
        "QEMU_IMG=$(command -v qemu-img || true)\n"
        "if [ ! -f \"$DISK\" ]; then\n"
        "  if [ \"$MODE\" = installed ]; then echo \"Installed-system disk not found: $DISK\" >&2; exit 4; fi\n"
        "  if [ -z \"$QEMU_IMG\" ]; then echo 'qemu-img not found; cannot create installer test disk' >&2; exit 4; fi\n"
        "  mkdir -p \"$(dirname -- \"$DISK\")\"\n"
        "  \"$QEMU_IMG\" create -f qcow2 \"$DISK\" \"$DISK_SIZE\"\n"
        "fi\n"
        "if [ \"$MODE\" = live ]; then VM_TITLE='Suret - LIVE ISO'; else VM_TITLE='Suret - INSTALLED SYSTEM'; fi\n"
        "ARGS=(-name \"$VM_TITLE\" -machine q35 \"${ACCEL[@]}\" -m \"${LINUX_ISO_QEMU_MEMORY:-4096}\" -smp \"${LINUX_ISO_QEMU_CPUS:-2}\" -drive \"file=$DISK,format=qcow2,if=virtio\" -netdev user,id=net0 -device virtio-net-pci,netdev=net0 -vga std -display gtk,gl=off)\n"
        "if [ \"$MODE\" = live ]; then ARGS+=(-boot d -cdrom \"$ISO\" -no-reboot); else ARGS+=(-boot c); fi\n"
        "if [ \"$FIRMWARE\" = uefi ]; then\n"
        "  CODE=\"\"; VARS=\"\"\n"
        "  for f in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/ovmf/OVMF.fd; do [ -f \"$f\" ] && CODE=\"$f\" && break; done\n"
        "  for f in /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd; do [ -f \"$f\" ] && VARS=\"$f\" && break; done\n"
        "  if [ -z \"$CODE\" ] || [ -z \"$VARS\" ]; then echo 'OVMF UEFI firmware not found. Install the ovmf package or set LINUX_ISO_QEMU_FIRMWARE=bios.' >&2; exit 3; fi\n"
        "  VARS_COPY=$(mktemp --tmpdir suret-OVMF-VARS.XXXXXX.fd)\n"
        "  trap 'rm -f \"$VARS_COPY\"' EXIT INT TERM\n"
        "  cp \"$VARS\" \"$VARS_COPY\"\n"
        "  ARGS+=(-drive \"if=pflash,format=raw,readonly=on,file=$CODE\" -drive \"if=pflash,format=raw,file=$VARS_COPY\")\n"
        "elif [ \"$FIRMWARE\" != bios ]; then\n"
        "  echo \"Unknown LINUX_ISO_QEMU_FIRMWARE: $FIRMWARE (use uefi or bios)\" >&2; exit 2\n"
        "fi\n"
        "if [ \"$MODE\" = live ]; then echo \"Booting live ISO ($FIRMWARE): $ISO\"; else echo \"Booting installed system ($FIRMWARE): $DISK\"; fi\n"
        "\"$QEMU\" \"${ARGS[@]}\"\n",
        encoding="utf-8",
    )
    qemu_sh.chmod(0o755)


def _select_backend(requested: str = "auto") -> str:
    if requested not in {"auto", "container", "boxbuild", "direct"}:
        raise BuilderError(f"Unknown build backend: {requested}")
    if requested == "container":
        if shutil.which("uv") is None:
            raise BuilderError("uv is required for direct container build")
        if shutil.which("podman") is None:
            raise BuilderError("podman is required for direct container build")
        return "container"
    if requested == "boxbuild":
        standalone = shutil.which("kiwi-boxbuild") is not None
        core = shutil.which("kiwi-ng") is not None and (
            shutil.which("qemu-system-x86_64") is not None or shutil.which("qemu-kvm") is not None
        )
        if shutil.which("podman") is None:
            raise BuilderError("podman is required for boxbuild")
        if not standalone and not core:
            raise BuilderError("boxbuild requires kiwi-boxbuild, or kiwi-ng plus QEMU")
        return "boxbuild"
    if requested == "direct":
        if shutil.which("kiwi-ng") is None:
            raise BuilderError("kiwi-ng is not installed")
        return "direct"
    if shutil.which("uv") and shutil.which("podman"):
        return "container"
    if shutil.which("podman") and (
        shutil.which("kiwi-boxbuild")
        or (shutil.which("kiwi-ng") and (shutil.which("qemu-system-x86_64") or shutil.which("qemu-kvm")))
    ):
        return "boxbuild"
    if shutil.which("kiwi-ng"):
        return "direct"
    raise BuilderError("No KIWI backend found; run 'linux-iso build-doctor' for details")


def run_kiwi_build(project: Path, backend: str = "auto") -> int:
    project = project.expanduser().resolve()
    if not (project / "config.xml").is_file():
        raise BuilderError(f"Not a staged KIWI project: {project}")
    selected = _select_backend(backend)
    env = dict(**__import__("os").environ)
    env["LINUX_ISO_BUILD_BACKEND"] = selected
    proc = subprocess.run([str(project / "build.sh")], cwd=project, env=env, check=False)
    return proc.returncode


def generate_kiwi_project(
    profile: Path,
    destination: Path,
    recipe_id: str = UBUNTU_2604_KDE.id,
) -> Path:
    profile = profile.expanduser().resolve()
    destination = destination.expanduser().resolve()
    manifest = _read_manifest(profile)
    verification = verify_profile(profile)
    if not verification.ok:
        detail = "; ".join(verification.errors[:4])
        if len(verification.errors) > 4:
            detail += f"; ... {len(verification.errors) - 4} more"
        raise BuilderError(f"Profile verification failed before ISO staging: {detail}")
    if recipe_id not in RECIPES:
        raise BuilderError(f"Unknown KIWI recipe: {recipe_id}")
    recipe = RECIPES[recipe_id]
    _validate_recipe_compatibility(manifest, recipe)

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    overlay = destination / "root"
    share_profile = overlay / "usr/share/linux-iso/profile"
    share_profile.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(profile, share_profile)

    generate_calamares_overlay(profile, overlay)
    _write_build_scripts(destination, recipe, manifest)
    _write_config_xml(destination / "config.xml", recipe, manifest)

    from linux_iso.portability import portability_report
    portability = portability_report(profile, recipe_id=recipe_id)
    if not portability.ready:
        detail = "; ".join(portability.blockers[:4])
        raise BuilderError(f"Profile portability check failed before ISO staging: {detail}")
    (destination / "PORTABILITY.txt").write_text(portability.render() + "\n", encoding="utf-8")

    required = _required_base_packages(manifest)
    marker = destination / "README-BUILDER.txt"
    marker.write_text(
        f"{PRODUCT_NAME} v{__version__} KIWI project\n"
        f"Recipe: {recipe.id}\n"
        f"Target Plasma: {recipe.target_plasma_version or 'unknown'}\n"
        f"Appearance packages embedded in base image: {len(required)}\n"
        "Live user: live (ephemeral media only)\n"
        "The captured profile is applied to the live session and again to the user created by Calamares.\n"
        "Run ./build.sh to build, then ./test-qemu.sh to boot the generated ISO.\n"
        "The generated recipe remains experimental until boot/install validation in QEMU succeeds.\n",
        encoding="utf-8",
    )
    return destination


def generate_kiwi_overlay(profile: Path, destination: Path) -> Path:
    """Backward-compatible name; v0.2+ stages a full KIWI project."""
    return generate_kiwi_project(profile, destination)
