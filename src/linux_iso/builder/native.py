from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import yaml

from linux_iso import __version__
from linux_iso.assets import sha256_file
from linux_iso.verification import verify_profile


class NativeIsoError(RuntimeError):
    pass


@dataclass
class NativeIsoProbe:
    base_iso: str
    distro_id: str
    distro_name: str
    distro_version: str | None
    architecture: str
    package_family: str
    live_rootfs: str
    kernel: str | None
    initrd: str | None
    installer: str
    desktop_hint: str | None = None
    boot_family: str = "grub"
    supports_native_build: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


PARDUS_KDE_REQUIRED_PACKAGES = [
    "kde-plasma-desktop",
    "sddm",
]

PARDUS_KDE_OPTIONAL_PACKAGES = [
    "plasma-nm",
    "plasma-pa",
    "powerdevil",
    "dolphin",
    "konsole",
    "systemsettings",
    "kinfocenter",
    "plasma-discover",
    "xdg-desktop-portal-kde",
    "kde-config-sddm",
    "breeze-cursor-theme",
]

# Kept as a compatibility/export alias for callers that only need the complete
# package set. Native installation itself treats the first two as mandatory.
PARDUS_KDE_PACKAGES = PARDUS_KDE_REQUIRED_PACKAGES + PARDUS_KDE_OPTIONAL_PACKAGES

PARDUS_XFCE_REMOVE_PACKAGES = [
    "pardus-xfce-desktop",
    "xfce4",
    "xfce4-session",
    "xfdesktop4",
    "xfce4-panel",
    "lightdm",
    "lightdm-gtk-greeter",
]

# Applications captured as distro packages can originate from an official
# vendor repository that is not present on a clean Pardus ISO. Native Mode
# should prefer the vendor's Debian-family package channel when one is known:
# this preserves the source package model, keeps normal APT updates working and
# avoids needlessly converting proprietary wrappers into Flatpak extra-data
# installs inside the remaster chroot.  The resolver IDs below are a strict
# allow-list; profile data can never inject an arbitrary repository.
VENDOR_APT_RESOLVERS: dict[str, dict[str, str]] = {
    "brave-browser": {
        "id": "brave-browser",
        "package": "brave-browser",
        "key_url": "https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg",
        "keyring": "/usr/share/keyrings/brave-browser-archive-keyring.gpg",
        "source_file": "/etc/apt/sources.list.d/brave-browser-release.sources",
        "source_url": "https://brave-browser-apt-release.s3.brave.com/brave-browser.sources",
        "source_line": "deb [arch=amd64 signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com stable main",
        "portable_exec": "",
    },
    "code": {
        "id": "microsoft-vscode",
        "package": "code",
        "key_url": "https://packages.microsoft.com/keys/microsoft.asc",
        "keyring": "/usr/share/keyrings/microsoft-vscode.gpg",
        "source_file": "/etc/apt/sources.list.d/vscode.list",
        "source_line": "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-vscode.gpg] https://packages.microsoft.com/repos/code stable main",
        "portable_exec": "flatpak run com.visualstudio.code",
    },
    "visual-studio-code": {
        "id": "microsoft-vscode",
        "package": "code",
        "key_url": "https://packages.microsoft.com/keys/microsoft.asc",
        "keyring": "/usr/share/keyrings/microsoft-vscode.gpg",
        "source_file": "/etc/apt/sources.list.d/vscode.list",
        "source_line": "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-vscode.gpg] https://packages.microsoft.com/repos/code stable main",
        "portable_exec": "flatpak run com.visualstudio.code",
    },
    "signal-desktop": {
        "id": "signal-desktop",
        "package": "signal-desktop",
        "key_url": "https://updates.signal.org/desktop/apt/keys.asc",
        "keyring": "/usr/share/keyrings/signal-desktop-keyring.gpg",
        "source_file": "/etc/apt/sources.list.d/signal-desktop.list",
        "source_line": "deb [arch=amd64 signed-by=/usr/share/keyrings/signal-desktop-keyring.gpg] https://updates.signal.org/desktop/apt xenial main",
        "portable_exec": "flatpak run org.signal.Signal",
    },
}

# Some applications are genuinely captured as Flatpak but rely on Flatpak
# `extra-data`, which downloads proprietary vendor payloads during installation.
# Pardus 25 currently ships a Flatpak branch affected by upstream 1.16.5
# /proc/self/fd regressions in this path. For known applications with an
# official Linux archive, Native Mode can install the vendor payload directly
# while preserving the visible application identity and desktop launcher.
# Resolver metadata remains code-owned: profile data cannot inject URLs or
# arbitrary install commands.
VENDOR_ARCHIVE_FLATPAK_RESOLVERS: dict[str, dict[str, str]] = {
    "com.google.AndroidStudio": {
        "id": "google-android-studio",
        "app_id": "com.google.AndroidStudio",
        "display_name": "Android Studio",
        "install_dir": "/opt/android-studio",
        "desktop_id": "com.google.AndroidStudio.desktop",
        "exec": "/opt/android-studio/bin/studio",
    },
}


def _split_vendor_archive_flatpaks(flatpaks: list[str]) -> tuple[list[str], list[str]]:
    vendor_archives: list[str] = []
    remaining: list[str] = []
    for app_id in flatpaks:
        spec = VENDOR_ARCHIVE_FLATPAK_RESOLVERS.get(app_id)
        if spec:
            resolver_id = spec["id"]
            if resolver_id not in vendor_archives:
                vendor_archives.append(resolver_id)
        elif app_id not in remaining:
            remaining.append(app_id)
    return vendor_archives, remaining

# Apps without a vetted vendor-native resolver can still use a portable Flatpak
# fallback.  Do not add Code/Signal here: their source APT packages now resolve
# through VENDOR_APT_RESOLVERS, while a profile that was *actually* Flatpak is
# preserved as Flatpak by _profile_app_plan().
PORTABLE_FLATPAK_FALLBACKS = {
    "steam": "com.valvesoftware.Steam",
    "steam-launcher": "com.valvesoftware.Steam",
    "discord": "com.discordapp.Discord",
    "spotify-client": "com.spotify.Client",
    "spotify": "com.spotify.Client",
    "obs-studio": "com.obsproject.Studio",
    "google-chrome-stable": "com.google.Chrome",
}

SNAP_FLATPAK_FALLBACKS = {
    **PORTABLE_FLATPAK_FALLBACKS,
    "code": "com.visualstudio.code",
    "visual-studio-code": "com.visualstudio.code",
    "signal-desktop": "org.signal.Signal",
}

ROOTFS_CANDIDATES = (
    "/live/filesystem.squashfs",
    "/casper/filesystem.squashfs",
    "/LiveOS/squashfs.img",
)


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeIsoError(f"Command failed: {' '.join(command)}: {exc}") from exc


def _require_tools(names: Iterable[str]) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise NativeIsoError(
            "Native ISO mode requires: " + ", ".join(missing) + ". "
            "Install the missing tools and retry."
        )


def _list_iso(iso: Path) -> set[str]:
    _require_tools(["xorriso"])
    proc = _run(["xorriso", "-indev", str(iso), "-find", "/", "-type", "f", "-exec", "echo", "--"], timeout=180)
    if proc.returncode != 0:
        raise NativeIsoError(f"Could not inspect ISO with xorriso: {proc.stderr.strip()}")
    result: set[str] = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("'") and line.endswith("'"):
            line = line[1:-1]
        if line.startswith("/"):
            result.add(line)
    return result


def _extract_small_file(iso: Path, source: str) -> str | None:
    _require_tools(["xorriso"])
    with tempfile.TemporaryDirectory(prefix="suret-iso-probe-") as tmp:
        target = Path(tmp) / Path(source).name
        proc = _run(
            ["xorriso", "-osirrox", "on", "-indev", str(iso), "-extract", source, str(target)],
            timeout=60,
        )
        if proc.returncode != 0 or not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None


def _probe_from_file_set(base: Path, files: set[str], info_text: str | None = None) -> NativeIsoProbe:
    rootfs = next((item for item in ROOTFS_CANDIDATES if item in files), None)
    if rootfs is None:
        raise NativeIsoError(
            "Unsupported live ISO layout. Expected one of: " + ", ".join(ROOTFS_CANDIDATES)
        )

    info = (info_text or "").strip()
    lower = f"{base.name} {info}".lower()
    distro_id = "unknown"
    distro_name = info or base.stem
    distro_version: str | None = None
    package_family = "unknown"
    installer = "unknown"
    desktop_hint: str | None = None
    supports = False

    if "pardus" in lower:
        distro_id = "pardus"
        distro_name = info or "Pardus"
        package_family = "apt"
        installer = "pardus-installer"
        match = re.search(r"pardus[- ]?(\d+(?:\.\d+)?)", lower, re.I)
        if match:
            distro_version = match.group(1)
        # The repository bootstrap and package policy below are intentionally
        # Pardus-25-specific. Do not silently claim a future release until it
        # has its own adapter/repository mapping.
        supports = rootfs == "/live/filesystem.squashfs" and bool(
            distro_version and distro_version.split(".", 1)[0] == "25"
        )
        if "xfce" in lower:
            desktop_hint = "xfce"
        elif "gnome" in lower:
            desktop_hint = "gnome"
    elif "ubuntu" in lower or rootfs.startswith("/casper/"):
        distro_id = "ubuntu"
        distro_name = info or "Ubuntu"
        package_family = "apt"
        installer = "native-ubuntu"
        match = re.search(r"(\d{2}\.\d{2})", lower)
        if match:
            distro_version = match.group(1)
    elif "fedora" in lower or rootfs.startswith("/LiveOS/"):
        distro_id = "fedora"
        distro_name = info or "Fedora"
        package_family = "dnf"
        installer = "anaconda"
        match = re.search(r"fedora[^0-9]*(\d+)", lower)
        if match:
            distro_version = match.group(1)

    kernel = None
    initrd = None
    for candidate in ("/live/vmlinuz", "/casper/vmlinuz", "/images/pxeboot/vmlinuz"):
        if candidate in files:
            kernel = candidate
            break
    for candidate in ("/live/initrd.img", "/casper/initrd", "/images/pxeboot/initrd.img"):
        if candidate in files:
            initrd = candidate
            break

    architecture = "x86_64" if any(token in lower for token in ("amd64", "x86_64")) else "unknown"
    if distro_id == "pardus" and architecture != "x86_64":
        supports = False
    return NativeIsoProbe(
        base_iso=str(base),
        distro_id=distro_id,
        distro_name=distro_name,
        distro_version=distro_version,
        architecture=architecture,
        package_family=package_family,
        live_rootfs=rootfs,
        kernel=kernel,
        initrd=initrd,
        installer=installer,
        desktop_hint=desktop_hint,
        supports_native_build=supports,
    )


def probe_iso_tree(tree: Path, *, label: str | None = None) -> NativeIsoProbe:
    """Probe an already extracted ISO tree. Primarily useful for tests and diagnostics."""
    tree = tree.resolve()
    if not tree.is_dir():
        raise NativeIsoError(f"ISO tree not found: {tree}")
    files = {"/" + p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file()}
    info_path = tree / ".disk/info"
    info = info_path.read_text(encoding="utf-8", errors="replace") if info_path.is_file() else label
    return _probe_from_file_set(Path(label or tree.name), files, info)


def probe_native_iso(base_iso: Path) -> NativeIsoProbe:
    base_iso = base_iso.expanduser().resolve()
    if not base_iso.is_file():
        raise NativeIsoError(f"Base ISO not found: {base_iso}")
    files = _list_iso(base_iso)
    info = _extract_small_file(base_iso, "/.disk/info")
    return _probe_from_file_set(base_iso, files, info)


def _load_manifest(profile: Path) -> dict:
    manifest_path = profile / "manifest.yaml"
    if not manifest_path.is_file():
        raise NativeIsoError(f"Profile manifest not found: {manifest_path}")
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


def _valid_native_package_name(name: str) -> bool:
    # Debian-family package names are deliberately conservative here. Besides
    # catching corrupt manifests, this prevents a package token beginning with
    # '-' from being interpreted as an apt option inside the generated chroot
    # installer. Optional :arch qualifiers are accepted.
    return re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?", name) is not None


def _valid_flatpak_id(name: str) -> bool:
    # Captured Flatpak application IDs are dot-separated identifiers. Refuse
    # whitespace, slashes and option-looking values before they reach flatpak.
    return (
        not name.startswith("-")
        and "/" not in name
        and re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", name) is not None
    )


def _profile_appearance_plan(manifest: dict, package_family: str) -> list[str]:
    required: list[str] = []
    for item in manifest.get("packages", []):
        if not item.get("required_for_appearance"):
            continue
        provider = str(item.get("provider") or "")
        name = str(item.get("name") or "").strip()
        if provider != package_family or not name:
            continue
        if package_family == "apt" and not _valid_native_package_name(name):
            raise NativeIsoError(f"Unsafe or invalid native package name in profile: {name!r}")
        if name not in required:
            required.append(name)
    return required


def _profile_app_plan(manifest: dict, package_family: str) -> tuple[list[str], list[str], list[str]]:
    native: list[str] = []
    vendor_apt: list[str] = []
    flatpaks: list[str] = []
    for item in manifest.get("packages", []):
        if not item.get("installer_visible", True):
            continue
        if item.get("required_for_appearance"):
            continue
        provider = str(item.get("provider") or "")
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        if provider == package_family:
            if package_family == "apt" and not _valid_native_package_name(name):
                raise NativeIsoError(f"Unsafe or invalid native package name in profile: {name!r}")
            vendor = VENDOR_APT_RESOLVERS.get(name) if package_family == "apt" else None
            if vendor:
                resolver_id = vendor["id"]
                if resolver_id not in vendor_apt:
                    vendor_apt.append(resolver_id)
                continue
            fallback = PORTABLE_FLATPAK_FALLBACKS.get(name)
            if fallback:
                if fallback not in flatpaks:
                    flatpaks.append(fallback)
                continue
            if name not in native:
                native.append(name)
        elif provider == "flatpak":
            if not _valid_flatpak_id(name):
                raise NativeIsoError(f"Unsafe or invalid Flatpak application ID in profile: {name!r}")
            if name not in flatpaks:
                flatpaks.append(name)
        elif provider == "snap":
            # Snap captures are cross-provider by definition. Prefer a vetted
            # portable Flatpak resolver; vendor APT is reserved for packages
            # that were natively managed by APT on the source system.
            fallback = SNAP_FLATPAK_FALLBACKS.get(name)
            if fallback:
                if fallback not in flatpaks:
                    flatpaks.append(fallback)
            else:
                raise NativeIsoError(
                    f"Captured Snap application {name!r} has no Native Pardus resolver yet. "
                    "Refusing to keep a launcher for an application that will not be installed."
                )
    return native, vendor_apt, flatpaks


BRAVE_NATIVE_EXECUTABLES = {"brave-browser", "brave-browser-stable", "brave"}


def _safe_webapp_url_from_portable_exec(command: str) -> str | None:
    """Return the URL from a capture-time xdg-open web-app fallback.

    Desktop Exec lines are not shell commands, but shlex is still useful for the
    constrained two-token form emitted by Suret. Refuse controls, whitespace in
    the URL, credentials, and non-HTTP(S) schemes before rendering the URL back
    into a launcher.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if len(tokens) != 2 or Path(tokens[0]).name != "xdg-open":
        return None
    url = tokens[1]
    if any(ord(ch) < 32 or ch.isspace() for ch in url):
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if any(ch in url for ch in {'"', "\\"}):
        return None
    return url


def _browser_binding_from_original_exec(command: str) -> tuple[str, str | None, str | None] | None:
    """Classify the source browser contract without preserving browser profile data.

    Returns ``(target_exec_prefix, vendor_apt_resolver, flatpak_app_id)``. Only
    code-owned browser identities are accepted; arbitrary commands from profile
    data are never re-emitted.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not tokens:
        return None
    executable = Path(tokens[0]).name
    if executable in BRAVE_NATIVE_EXECUTABLES:
        return ("/usr/bin/brave-browser", "brave-browser", None)
    if executable == "flatpak" and "com.brave.Browser" in tokens:
        return ("flatpak run com.brave.Browser", None, "com.brave.Browser")
    return None


def _desktop_exec_url(url: str) -> str:
    # In the Desktop Entry Exec grammar '%' introduces a field code. Doubling
    # it preserves literal percent escapes such as %20 in URLs.
    return url.replace("%", "%%")


def _rewrite_native_webapp_launchers(profile_copy: Path) -> dict[str, object]:
    """Preserve browser affinity for captured web apps without copying profiles.

    Older Suret profiles deliberately normalized ChatGPT/WhatsApp PWA launchers
    to ``xdg-open URL`` and stored the original browser command in a reversible
    marker. Native Mode can use that marker to recover *which browser* owned the
    web app while discarding profile-directory/app-id state (which depends on
    sensitive browser profile storage that Suret must never copy). The target
    launcher uses Chromium/Brave's profile-independent ``--app=URL`` mode.
    """
    result: dict[str, object] = {
        "rewritten": 0,
        "vendor_apt_apps": [],
        "flatpaks": [],
        "browsers": {},
    }
    payload = profile_copy / "payload"
    if not payload.is_dir():
        return result

    vendor_apt: set[str] = set()
    flatpaks: set[str] = set()
    browsers: dict[str, int] = {}
    rewritten = 0

    for path in payload.rglob("*.desktop"):
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = raw.splitlines(keepends=True)
        out: list[str] = []
        i = 0
        changed = False
        path_binding: tuple[str, str | None, str | None] | None = None
        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip("\r\n")
            if stripped.startswith("Exec=") and i + 1 < len(lines):
                marker = lines[i + 1].rstrip("\r\n")
                prefix = "X-Suret-Original-Exec-B64="
                if marker.startswith(prefix):
                    current = stripped.split("=", 1)[1].strip()
                    url = _safe_webapp_url_from_portable_exec(current)
                    encoded = marker[len(prefix):].strip()
                    try:
                        original = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
                    except (ValueError, UnicodeDecodeError):
                        original = ""
                    binding = _browser_binding_from_original_exec(original) if url else None
                    if binding is not None and url is not None:
                        target_prefix, vendor_id, flatpak_id = binding
                        newline = line[len(stripped):]
                        out.append(f"Exec={target_prefix} --app={_desktop_exec_url(url)}{newline}")
                        i += 2  # Drop the Suret-only reversible marker.
                        rewritten += 1
                        changed = True
                        path_binding = binding
                        if vendor_id:
                            vendor_apt.add(vendor_id)
                            browsers["brave-native"] = browsers.get("brave-native", 0) + 1
                        if flatpak_id:
                            flatpaks.add(flatpak_id)
                            browsers["brave-flatpak"] = browsers.get("brave-flatpak", 0) + 1
                        continue
            out.append(line)
            i += 1

        if changed and path_binding is not None:
            _target_prefix, vendor_id, flatpak_id = path_binding
            final: list[str] = []
            saw_tryexec = False
            for line in out:
                stripped = line.rstrip("\r\n")
                newline = line[len(stripped):]
                if stripped.startswith("TryExec="):
                    saw_tryexec = True
                    if vendor_id == "brave-browser":
                        final.append(f"TryExec=/usr/bin/brave-browser{newline}")
                    elif flatpak_id == "com.brave.Browser":
                        final.append(f"TryExec=flatpak{newline}")
                    else:
                        final.append(line)
                    continue
                # The source app-id belongs to a browser profile registry that is
                # intentionally not copied. Keeping crx_<app-id> would mislead
                # Plasma's task matching after switching to --app=URL.
                if stripped.startswith("StartupWMClass=crx_"):
                    continue
                final.append(line)
            if not saw_tryexec:
                insertion = 1 if final and final[0].startswith("[Desktop Entry]") else 0
                tryexec = "/usr/bin/brave-browser" if vendor_id == "brave-browser" else "flatpak"
                final.insert(insertion, f"TryExec={tryexec}\n")
            path.write_text("".join(final), encoding="utf-8")

    result["rewritten"] = rewritten
    result["vendor_apt_apps"] = sorted(vendor_apt)
    result["flatpaks"] = sorted(flatpaks)
    result["browsers"] = browsers
    return result


def _restore_native_launcher_execs(profile_copy: Path, *, restore_portable_execs: set[str] | None = None) -> int:
    """Undo generic cross-distro launcher translations for native builds.

    Capture keeps a reversible X-Suret-Original-Exec-B64 marker whenever it
    translates an Exec line. In a same-distro native remaster, distro-native
    commands (for example pardus-about and pardus-mycomputer) should remain
    native. Portable web/Flatpak replacements are intentionally retained.
    """
    count = 0
    restore_portable_execs = restore_portable_execs or set()
    payload = profile_copy / "payload"
    if not payload.is_dir():
        return 0
    for path in payload.rglob("*.desktop"):
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = raw.splitlines(keepends=True)
        out: list[str] = []
        i = 0
        changed = False
        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip("\r\n")
            if stripped.startswith("Exec=") and i + 1 < len(lines):
                marker = lines[i + 1].rstrip("\r\n")
                prefix = "X-Suret-Original-Exec-B64="
                if marker.startswith(prefix):
                    current = stripped.split("=", 1)[1].strip()
                    encoded = marker[len(prefix):].strip()
                    try:
                        original = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
                    except (ValueError, UnicodeDecodeError):
                        original = ""
                    # Web-app launchers stay portable. Flatpak fallbacks also
                    # stay portable unless the Native application plan resolved
                    # that exact fallback back to an official vendor APT package.
                    portable = current.startswith("xdg-open ") or current.startswith("flatpak run ")
                    restore_current = current in restore_portable_execs
                    should_restore = bool(original) and (not portable or restore_current)
                    newline = line[len(stripped):]
                    out.append(f"Exec={original}{newline}" if should_restore else line)
                    i += 2  # Drop the Suret-only metadata line from final profile.
                    if should_restore:
                        count += 1
                    changed = True
                    continue
            out.append(line)
            i += 1
        if changed:
            path.write_text("".join(out), encoding="utf-8")
    return count


def _rewrite_vendor_archive_launcher_execs(profile_copy: Path, resolver_ids: set[str]) -> int:
    """Rewrite only desktop entries belonging to a vetted vendor-archive app.

    Exported Flatpak desktop files often use a generic ``TryExec=flatpak``.
    Never rewrite that line merely because some other vendor archive exists in
    the profile: first identify the desktop entry by app ID / desktop filename,
    then update its Exec/TryExec pair.
    """
    if not resolver_ids:
        return 0
    specs = [
        spec for spec in VENDOR_ARCHIVE_FLATPAK_RESOLVERS.values()
        if spec["id"] in resolver_ids
    ]
    if not specs:
        return 0
    payload = profile_copy / "payload"
    if not payload.is_dir():
        return 0
    count = 0
    for path in payload.rglob("*.desktop"):
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        matching = next(
            (
                spec for spec in specs
                if spec["app_id"] in raw
                or path.name == spec["desktop_id"]
                or path.stem == spec["app_id"]
            ),
            None,
        )
        if matching is None:
            continue
        app_id = matching["app_id"]
        native_exec = matching["exec"]
        lines = raw.splitlines(keepends=True)
        changed = False
        out: list[str] = []
        for line in lines:
            stripped = line.rstrip("\r\n")
            newline = line[len(stripped):]
            if stripped.startswith("Exec="):
                current = stripped.split("=", 1)[1]
                if app_id in current and "flatpak" in current:
                    field_code = (
                        " %U" if "%U" in current else
                        " %F" if "%F" in current else
                        " %u" if "%u" in current else
                        " %f" if "%f" in current else
                        ""
                    )
                    line = f"Exec={native_exec}{field_code}{newline}"
                    changed = True
                    count += 1
            elif stripped.startswith("TryExec="):
                current = stripped.split("=", 1)[1].strip()
                if app_id in current or current in {"flatpak", "/usr/bin/flatpak"}:
                    line = f"TryExec={native_exec}{newline}"
                    changed = True
            out.append(line)
        if changed:
            path.write_text("".join(out), encoding="utf-8")
    return count


def _normalize_architecture(value: object) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "amd64": "x86_64",
        "x86-64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
    }
    return aliases.get(raw, raw)


def _version_major(value: object) -> str | None:
    match = re.search(r"(\d+)", str(value or ""))
    return match.group(1) if match else None


def _safe_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


NATIVE_FIRST_LOGIN = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

PROFILE = Path("/usr/share/linux-iso/profile")
STATE = PROFILE / "native-restore.json"
TARGET_USER = Path("/var/lib/linux-iso/target-user")
LIVE_TARGET_USER = Path("/run/linux-iso/target-user")
MARKER = Path.home() / ".local/state/linux-iso/native-profile-v1.done"
PRELOGIN_MARKER = Path.home() / ".local/state/linux-iso/native-prelogin-v1.done"
TEXT_SUFFIXES = {"", ".conf", ".ini", ".rc", ".list", ".desktop", ".profile", ".toml", ".fish", ".zsh", ".bash", ".json", ".xml", ".qml"}


def profile_fingerprint() -> str:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "legacy"
    return str(data.get("profile_fingerprint") or "legacy")


def marker_matches(path: Path, fingerprint: str) -> bool:
    try:
        return path.is_file() and path.read_text(encoding="utf-8").strip() == fingerprint
    except OSError:
        return False


def rewrite_home(path: Path, home: Path) -> None:
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        return
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    updated = raw.replace("{{HOME}}", str(home))
    if updated != raw:
        path.write_text(updated, encoding="utf-8")


def run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass


def is_target_user() -> bool:
    username = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    for marker in (LIVE_TARGET_USER, TARGET_USER):
        if marker.is_file():
            try:
                return marker.read_text(encoding="utf-8").strip() == username
            except OSError:
                return False
    # Fallback if the pre-login service did not get a chance to persist the
    # target marker: only the lowest eligible local interactive UID may apply
    # the machine profile. Never fan the profile out to every account.
    try:
        import pwd
        candidates = [
            entry for entry in pwd.getpwall()
            if 1000 <= entry.pw_uid < 60000
            and entry.pw_dir.startswith("/home/")
            and entry.pw_shell not in {"/usr/sbin/nologin", "/sbin/nologin", "/bin/false"}
        ]
    except OSError:
        return False
    return bool(candidates and min(candidates, key=lambda entry: entry.pw_uid).pw_name == username)


def safe_destination(home: Path, rel: Path) -> Path | None:
    dst = home / rel
    current = home
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            return None
    if dst.is_symlink():
        try:
            dst.unlink()
        except OSError:
            return None
    return dst


def main() -> int:
    if not STATE.is_file() or not is_target_user():
        return 0
    fingerprint = profile_fingerprint()
    if marker_matches(MARKER, fingerprint):
        return 0
    home = Path.home().resolve()
    payload = PROFILE / "payload/home"

    # The system pre-login service normally installs the payload before the
    # display manager paints the first frame. If that already happened, do not
    # copy the whole profile again after Plasma starts; only refresh runtime
    # caches below. This avoids a visible first-login wallpaper/theme jump.
    if not marker_matches(PRELOGIN_MARKER, fingerprint) and payload.is_dir():
        for src in payload.rglob("*"):
            rel = src.relative_to(payload)
            dst = safe_destination(home, rel)
            if dst is None:
                continue
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            rewrite_home(dst, home)

    avatar = home / ".face"
    if avatar.is_file():
        run(["dbus-send", "--system", "--dest=org.freedesktop.Accounts", "--type=method_call", "/org/freedesktop/Accounts", "org.freedesktop.Accounts.FindUserByName", f"string:{os.environ.get('USER','')}"])

    run(["kbuildsycoca6"])
    run(["kbuildsycoca5"])
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(fingerprint + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

NATIVE_PRELOGIN = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
from pathlib import Path

PROFILE = Path("/usr/share/linux-iso/profile")
STATE = PROFILE / "native-restore.json"
PAYLOAD = PROFILE / "payload/home"
TARGET_USER = Path("/var/lib/linux-iso/target-user")
LIVE_TARGET_USER = Path("/run/linux-iso/target-user")
TEXT_SUFFIXES = {"", ".conf", ".ini", ".rc", ".list", ".desktop", ".profile", ".toml", ".fish", ".zsh", ".bash", ".json", ".xml", ".qml"}


def profile_fingerprint() -> str:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "legacy"
    return str(data.get("profile_fingerprint") or "legacy")


def marker_matches(path: Path, fingerprint: str) -> bool:
    try:
        return path.is_file() and path.read_text(encoding="utf-8").strip() == fingerprint
    except OSError:
        return False


def rewrite_home(path: Path, home: Path) -> None:
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        return
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    updated = raw.replace("{{HOME}}", str(home))
    if updated != raw:
        path.write_text(updated, encoding="utf-8")


def _chown(path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid, follow_symlinks=False)
    except OSError:
        pass


def _ensure_owned_parents(path: Path, home: Path, uid: int, gid: int) -> None:
    current = path
    while current != home and home in current.parents:
        _chown(current, uid, gid)
        current = current.parent


def safe_destination(home: Path, rel: Path) -> Path | None:
    dst = home / rel
    current = home
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            return None
    if dst.is_symlink():
        try:
            dst.unlink()
        except OSError:
            return None
    return dst


def copy_profile(home: Path, uid: int, gid: int, username: str, fingerprint: str) -> None:
    marker = home / ".local/state/linux-iso/native-prelogin-v1.done"
    if marker_matches(marker, fingerprint) or not PAYLOAD.is_dir():
        return
    for src in PAYLOAD.rglob("*"):
        rel = src.relative_to(PAYLOAD)
        dst = safe_destination(home, rel)
        if dst is None:
            continue
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            rewrite_home(dst, home)
        # Only claim paths created or overwritten by Suret. Recursively chowning
        # an existing home can alter unrelated personal files or mounted data.
        _chown(dst, uid, gid)
        _ensure_owned_parents(dst.parent, home, uid, gid)
    avatar = home / ".face"
    if avatar.is_file():
        icons = Path("/var/lib/AccountsService/icons")
        users = Path("/var/lib/AccountsService/users")
        try:
            icons.mkdir(parents=True, exist_ok=True)
            users.mkdir(parents=True, exist_ok=True)
            icon_dst = icons / username
            shutil.copy2(avatar, icon_dst)
            os.chmod(icon_dst, 0o644)
            user_file = users / username
            current = user_file.read_text(encoding="utf-8", errors="replace") if user_file.is_file() else "[User]\n"
            lines = [line for line in current.splitlines() if not line.startswith("Icon=")]
            if not lines or lines[0].strip() != "[User]":
                lines.insert(0, "[User]")
            lines.append(f"Icon={icon_dst}")
            user_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
    # User-local fonts must be visible before the first Plasma session paints
    # panel text (for example the digital-clock font).
    if (home / ".local/share/fonts").is_dir() or (home / ".fonts").is_dir():
        try:
            subprocess.run(["runuser", "-u", username, "--", "fc-cache", "-f"], check=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(fingerprint + "\n", encoding="utf-8")
    _chown(marker.parent, uid, gid)
    _ensure_owned_parents(marker.parent, home, uid, gid)
    _chown(marker, uid, gid)


def eligible_users() -> list[pwd.struct_passwd]:
    users = []
    for entry in pwd.getpwall():
        if not (1000 <= entry.pw_uid < 60000):
            continue
        if not entry.pw_dir.startswith("/home/"):
            continue
        if entry.pw_shell in {"/usr/sbin/nologin", "/sbin/nologin", "/bin/false"}:
            continue
        if Path(entry.pw_dir).is_dir():
            users.append(entry)
    return sorted(users, key=lambda entry: entry.pw_uid)


def live_boot() -> bool:
    if Path("/run/live/medium").exists():
        return True
    try:
        return "boot=live" in Path("/proc/cmdline").read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        return False


def target_user(marker: Path) -> pwd.struct_passwd | None:
    if marker.is_file():
        try:
            name = marker.read_text(encoding="utf-8").strip()
            entry = pwd.getpwnam(name)
            if entry in eligible_users():
                return entry
        except (OSError, KeyError):
            pass
    users = eligible_users()
    return users[0] if users else None


def main() -> int:
    fingerprint = profile_fingerprint()
    # Native Suret is a single-profile remaster. Apply it to one primary local
    # interactive account only; never overwrite every account on a multi-user
    # installation. Live media keeps its target marker in /run so an ephemeral
    # live username can never leak into an installed target filesystem.
    marker = LIVE_TARGET_USER if live_boot() else TARGET_USER
    entry = target_user(marker)
    if entry is None:
        return 0
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(entry.pw_name + "\n", encoding="utf-8")
    copy_profile(Path(entry.pw_dir), entry.pw_uid, entry.pw_gid, entry.pw_name, fingerprint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


NATIVE_PRELOGIN_SERVICE = '''[Unit]
Description=Apply Suret native desktop profile before first graphical login
After=local-fs.target
Before=display-manager.service
ConditionPathExists=/usr/share/linux-iso/profile/manifest.yaml

[Service]
Type=oneshot
ExecStart=/usr/lib/linux-iso/native-prelogin.py
RemainAfterExit=yes

[Install]
WantedBy=graphical.target
'''


NATIVE_SYSTEM_VISUAL = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path, PurePosixPath

PROFILE = Path("/usr/share/linux-iso/profile")
META = PROFILE / "system-visual.json"
PAYLOAD = PROFILE / "payload/system"


def clean_ini_value(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw or len(raw) > 512 or any(ch in raw for ch in "\r\n\0"):
        return None
    return raw


def safe_component_name(value: object) -> str | None:
    raw = clean_ini_value(value)
    if raw is None or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", raw) is None:
        return None
    return raw


def safe_relative_file(value: object) -> Path | None:
    raw = clean_ini_value(value)
    if raw is None:
        return None
    posix = PurePosixPath(raw)
    if posix.is_absolute() or not posix.parts or ".." in posix.parts:
        return None
    return Path(*posix.parts)


def grub_assignment(key: str, value: object) -> str | None:
    raw = clean_ini_value(value)
    if raw is None:
        return None
    return f"{key}={shlex.quote(raw)}"


def copy_tree(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.is_dir():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return True


def strip_ini_keys(path: Path, section_name: str, keys: set[str]) -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    section = ""
    kept: list[str] = []
    changed = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            kept.append(line)
            continue
        if section == section_name.lower() and "=" in line and not stripped.startswith(("#", ";")):
            key = line.split("=", 1)[0].strip()
            if key in keys:
                changed = True
                continue
        kept.append(line)
    if changed:
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def neutralize_sddm_theme_overrides() -> None:
    keys = {"Current", "CursorTheme", "CursorSize", "Font", "ThemeDir"}
    confd = Path("/etc/sddm.conf.d")
    if confd.is_dir():
        for path in sorted(confd.iterdir()):
            if path.is_file() and path.name != "10-suret-source-theme.conf":
                strip_ini_keys(path, "Theme", keys)
    strip_ini_keys(Path("/etc/sddm.conf"), "Theme", keys)


def main() -> int:
    if not META.is_file():
        return 0
    data = json.loads(META.read_text(encoding="utf-8"))
    grub = data.get("grub") or {}
    settings = grub.get("settings") or {}
    grub_lines = []
    if grub.get("theme_captured") and copy_tree(PAYLOAD / "grub/theme", Path("/boot/grub/themes/suret-source")):
        theme_file = safe_relative_file(grub.get("theme_file") or "theme.txt")
        if theme_file is not None:
            theme_path = Path("/boot/grub/themes/suret-source") / theme_file
            if theme_path.is_file():
                line = grub_assignment("GRUB_THEME", str(theme_path))
                if line:
                    grub_lines.append(line)
    bg_files = list((PAYLOAD / "grub").glob("background.*")) if (PAYLOAD / "grub").is_dir() else []
    if bg_files:
        bg_dst = Path("/boot/grub") / ("suret-source-background" + bg_files[0].suffix)
        shutil.copy2(bg_files[0], bg_dst)
        line = grub_assignment("GRUB_BACKGROUND", str(bg_dst))
        if line:
            grub_lines.append(line)
    for key in ("GRUB_GFXMODE", "GRUB_GFXPAYLOAD_LINUX", "GRUB_TIMEOUT_STYLE", "GRUB_TIMEOUT"):
        line = grub_assignment(key, settings.get(key))
        if line:
            grub_lines.append(line)
    if grub_lines:
        cfg = Path("/etc/default/grub.d/90-suret-visual.cfg")
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("\n".join(grub_lines) + "\n", encoding="utf-8")

    sddm = data.get("sddm") or {}
    sddm_settings = sddm.get("settings") or {}

    # SDDM runs before a user home is active. Promote the captured active
    # cursor theme and fonts to system-visible locations so the login screen
    # does not briefly use a different cursor/font and then switch at login.
    cursor = safe_component_name(sddm_settings.get("CursorTheme"))
    if cursor:
        for candidate in (
            PROFILE / "payload/home/.local/share/icons" / cursor,
            PROFILE / "payload/home/.icons" / cursor,
        ):
            if candidate.is_dir():
                copy_tree(candidate, Path("/usr/share/icons") / cursor)
                break
    promoted_fonts = False
    for fonts_src, fonts_dst in (
        (PROFILE / "payload/home/.local/share/fonts", Path("/usr/local/share/fonts/suret-profile")),
        (PROFILE / "payload/home/.fonts", Path("/usr/local/share/fonts/suret-profile-legacy")),
    ):
        if fonts_src.is_dir():
            copy_tree(fonts_src, fonts_dst)
            promoted_fonts = True
    if promoted_fonts:
        try:
            subprocess.run(["fc-cache", "-f"], check=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass

    sddm_lines = ["[Theme]"]
    if sddm.get("theme_captured"):
        theme_dst = Path("/usr/share/sddm/themes/suret-source")
        if not copy_tree(PAYLOAD / "sddm/theme", theme_dst):
            print("Suret: captured SDDM theme could not be restored", flush=True)
            return 20
        if not (theme_dst / "Main.qml").is_file():
            print("Suret: restored SDDM theme is missing Main.qml", flush=True)
            return 21
        sddm_lines.append("ThemeDir=/usr/share/sddm/themes")
        sddm_lines.append("Current=suret-source")
    font = clean_ini_value(sddm_settings.get("Font"))
    if cursor:
        sddm_lines.append(f"CursorTheme={cursor}")
    cursor_size = clean_ini_value(sddm_settings.get("CursorSize"))
    if cursor_size and cursor_size.isdigit():
        sddm_lines.append(f"CursorSize={cursor_size}")
    if font:
        sddm_lines.append(f"Font={font}")
    if len(sddm_lines) > 1:
        # Base ISO config can otherwise override the restored theme after this
        # script writes a drop-in. Remove only competing [Theme] keys, leaving
        # autologin/session/other SDDM settings untouched. The low-numbered
        # Suret file gives the restored first-boot state while allowing a later
        # kde_settings.conf written by System Settings to override it normally.
        neutralize_sddm_theme_overrides()
        cfg = Path("/etc/sddm.conf.d/10-suret-source-theme.conf")
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("\n".join(sddm_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


NATIVE_VENDOR_ARCHIVE_HELPER = r'''#!/usr/bin/env python3
from __future__ import annotations

import html
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

ANDROID_FILENAME_RE = re.compile(r"android-studio-[A-Za-z0-9._-]+-linux\.tar\.gz")
SHA256_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
ALLOWED_ANDROID_HOSTS = {"edgedl.me.gvt1.com", "redirector.gvt1.com", "dl.google.com"}


def _safe_google_url(url: str, filename: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in ALLOWED_ANDROID_HOSTS
        and Path(parsed.path).name == filename
    )


def parse_android_metadata(page_path: Path, out_path: Path) -> None:
    raw = page_path.read_text(encoding="utf-8", errors="replace")
    text = html.unescape(raw).replace("\\/", "/")
    # Prefer the official downloads table. The page repeats the package name in
    # license dialogs later; selecting from the table keeps filename/checksum
    # pairing deterministic even when several releases appear in the HTML.
    lower = text.lower()
    start = lower.find("android studio downloads")
    scope = text[start:] if start >= 0 else text

    for match in ANDROID_FILENAME_RE.finditer(scope):
        filename = match.group(0)
        # The downloads table places size then SHA-256 in the same row. Prefer
        # that row boundary when raw HTML is available; otherwise keep a narrow
        # following window. Do not de-duplicate filenames before a complete
        # filename+checksum+URL candidate is found because the page repeats the
        # same filename in UI data and in the visible downloads table.
        tail = scope[match.end(): match.end() + 1600]
        row_end = tail.lower().find("</tr>")
        after = tail[:row_end] if row_end >= 0 else tail
        sha_match = SHA256_RE.search(after)
        if sha_match is None:
            continue
        sha256 = sha_match.group(0).lower()

        url_pattern = re.compile(
            r"https://(?:edgedl\.me\.gvt1\.com|redirector\.gvt1\.com|dl\.google\.com)/"
            r"""[^"'<>\s]*""" + re.escape(filename)
        )
        url_match = url_pattern.search(text)
        if url_match is None:
            continue
        url = url_match.group(0)
        if not _safe_google_url(url, filename):
            continue
        out_path.write_text(f"{url}\t{sha256}\t{filename}\n", encoding="utf-8")
        return
    raise SystemExit("no safely paired official Android Studio Linux archive metadata found")


def _safe_link_target(member_name: str, link_name: str) -> bool:
    path = PurePosixPath(member_name)
    target = PurePosixPath(link_name)
    if target.is_absolute():
        return False
    combined = path.parent.joinpath(target)
    stack: list[str] = []
    for part in combined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                return False
            stack.pop()
        else:
            stack.append(part)
    return bool(stack and stack[0] == "android-studio")


def extract_android_archive(archive: Path, root: Path) -> None:
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        if not members:
            raise SystemExit("empty Android Studio archive")
        for member in members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or not path.parts
                or path.parts[0] != "android-studio"
                or ".." in path.parts
            ):
                raise SystemExit(f"unsafe archive member: {member.name}")
            if member.isdev() or member.isfifo():
                raise SystemExit(f"unsafe special archive member: {member.name}")
            if member.mode & 0o6000:
                raise SystemExit(f"unsafe privileged archive mode: {member.name}")
            if (member.issym() or member.islnk()) and not _safe_link_target(member.name, member.linkname):
                raise SystemExit(f"unsafe escaping archive link: {member.name}")
        # Python 3.12+ data filter strips unsafe ownership/permission metadata.
        # Pardus 25 ships a new enough Python. Keep the explicit checks above so
        # this remains fail-closed if tar semantics change.
        tf.extractall(root, filter="data")


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: native-vendor-archive.py <parse-android-metadata|extract-android> ...")
    cmd = sys.argv[1]
    if cmd == "parse-android-metadata" and len(sys.argv) == 4:
        parse_android_metadata(Path(sys.argv[2]), Path(sys.argv[3]))
        return 0
    if cmd == "extract-android" and len(sys.argv) == 4:
        extract_android_archive(Path(sys.argv[2]), Path(sys.argv[3]))
        return 0
    raise SystemExit("invalid native vendor archive helper invocation")


if __name__ == "__main__":
    raise SystemExit(main())
'''

NATIVE_BUILD_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail

# Desktop sessions may omit sbin directories although required tools are installed.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

HERE=$(cd -- "$(dirname -- "$0")" && pwd)
META="$HERE/native.json"
DEFAULT_BASE_ISO=__BASE_ISO_Q__
DEFAULT_RESULT=__RESULT_Q__
BASE_ISO=${LINUX_ISO_BASE_ISO:-"$DEFAULT_BASE_ISO"}
RESULT=${LINUX_ISO_NATIVE_RESULT:-"$DEFAULT_RESULT"}
WORK=${LINUX_ISO_NATIVE_WORK:-"$HERE/work"}
ISO_ROOT="$WORK/iso-root"
ROOTFS="$WORK/rootfs"
ROOTFS_REL="__ROOTFS_REL__"
LIVE_DIR=$(dirname "$ROOTFS_REL")
PROFILE="$HERE/profile"
OUT_ISO="$RESULT/__OUTPUT_NAME__"
TMP_ISO="${OUT_ISO}.partial"
REPLACE_DESKTOP=__REPLACE_DESKTOP__

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required tool: $1" >&2; exit 2; }; }
for tool in xorriso unsquashfs mksquashfs rsync chroot mount umount readlink stat df du tee awk grep find sort xargs md5sum sha256sum mv install cp rm sudo; do need "$tool"; done
[[ -f "$BASE_ISO" ]] || { echo "Base ISO not found: $BASE_ISO" >&2; exit 2; }
BASE_ISO=$(readlink -f -- "$BASE_ISO")
WORK=$(readlink -m -- "$WORK")
RESULT=$(readlink -m -- "$RESULT")
ISO_ROOT="$WORK/iso-root"
ROOTFS="$WORK/rootfs"
OUT_ISO="$RESULT/__OUTPUT_NAME__"
TMP_ISO="${OUT_ISO}.partial"

guard_destructive_dir() {
  local target=$1
  case "$target" in
    ""|/|/home|/root|/usr|/var|/etc|/opt|/srv|/tmp|/mnt|/media|"${HOME:-/__no_home__}")
      echo "Refusing destructive Native work path: $target" >&2
      exit 2
      ;;
  esac
}
guard_destructive_dir "$WORK"
path_within() {
  local child=$1 parent=$2
  [[ "$child" == "$parent" || "$child" == "$parent/"* ]]
}
if path_within "$RESULT" "$WORK"; then
  echo "Refusing Native paths: result directory must not be inside the disposable work tree." >&2
  exit 2
fi
if path_within "$HERE" "$WORK"; then
  echo "Refusing Native paths: work tree must not contain the staged Native project." >&2
  exit 2
fi
if path_within "$PROFILE" "$WORK"; then
  echo "Refusing Native paths: work tree must not contain the staged profile." >&2
  exit 2
fi
if path_within "$BASE_ISO" "$WORK"; then
  echo "Refusing Native paths: work tree must not contain the base ISO." >&2
  exit 2
fi

sudo -v
mkdir -p "$RESULT"
BUILD_LOG="$RESULT/native-build.log"
: > "$BUILD_LOG"
exec > >(tee -a "$BUILD_LOG") 2>&1
echo "Native build log: $BUILD_LOG"

BASE_STAMP=$(stat -Lc '%d:%i:%s:%Y' "$BASE_ISO")
BUILD_FINISHED=0
WORK_ORIG_UID=""
WORK_ORIG_GID=""
WORK_ORIG_MODE=""
WORK_SEALED=0

sanitize_build_privileges() (
  set +e
  for bwrap_path in "$ROOTFS/usr/bin/bwrap" "$ROOTFS/usr/libexec/flatpak-bwrap"; do
    [[ -e "$bwrap_path" ]] || continue
    sudo chmod u-s "$bwrap_path" >/dev/null 2>&1 || true
  done
)

seal_work_tree() {
  [[ -n "$WORK_ORIG_UID" && -n "$WORK_ORIG_GID" && -n "$WORK_ORIG_MODE" ]] || {
    echo "Cannot seal Native work tree before ownership metadata is recorded" >&2
    return 1
  }
  (( WORK_SEALED == 0 )) || return 0
  sudo chown root:root "$WORK"
  sudo chmod 0700 "$WORK"
  WORK_SEALED=1
}

unseal_work_tree() {
  [[ -n "$WORK_ORIG_UID" && -n "$WORK_ORIG_GID" && -n "$WORK_ORIG_MODE" ]] || return 0
  sanitize_build_privileges
  sudo chown "$WORK_ORIG_UID:$WORK_ORIG_GID" "$WORK" >/dev/null 2>&1 || true
  sudo chmod "$WORK_ORIG_MODE" "$WORK" >/dev/null 2>&1 || true
  WORK_SEALED=0
}

restore_resolver() (
  set +e
  sudo rm -f "$ROOTFS/etc/resolv.conf"
  if [[ -e "$ROOTFS/etc/resolv.conf.suret-backup" || -L "$ROOTFS/etc/resolv.conf.suret-backup" ]]; then
    sudo mv "$ROOTFS/etc/resolv.conf.suret-backup" "$ROOTFS/etc/resolv.conf"
  fi
)

cleanup_mounts() (
  set +e
  [[ -d "$ROOTFS" && ! -L "$ROOTFS" ]] || return 0
  for path in run sys proc dev; do
    [[ -L "$ROOTFS/$path" ]] && continue
    sudo umount -R -l "$ROOTFS/$path" >/dev/null 2>&1 || true
  done
  # v0.5.8 bind-mounts ROOTFS onto itself so that chroot / is a real mount
  # point. bubblewrap needs this for its recursive mount-propagation setup.
  sudo umount -l "$ROOTFS" >/dev/null 2>&1 || true
)

cleanup_chroot() (
  set +e
  sudo rm -f "$ROOTFS/tmp/linux-iso-native-install.sh"
  restore_resolver
  sanitize_build_privileges
  cleanup_mounts
  unseal_work_tree
)

on_exit() {
  local rc=$?
  trap - EXIT
  cleanup_chroot || true
  if (( BUILD_FINISHED == 0 )); then
    rm -f "$TMP_ISO"
    if (( rc != 0 )); then
      echo "Native build failed (exit $rc). Work tree kept for diagnostics: $WORK" >&2
      echo "Build log kept at: $BUILD_LOG" >&2
    fi
  fi
  exit "$rc"
}
trap on_exit EXIT

# A direct rerun of build-native.sh may inherit stale chroot mounts from an
# interrupted previous attempt. Detach them before privileged recursive reset
# and never cross filesystem boundaries while removing the disposable work tree.
cleanup_mounts
sudo rm -rf --one-file-system -- "$WORK"
mkdir -p "$WORK" "$ISO_ROOT" "$ROOTFS"
WORK_ORIG_UID=$(stat -Lc '%u' "$WORK")
WORK_ORIG_GID=$(stat -Lc '%g' "$WORK")
WORK_ORIG_MODE=$(stat -Lc '%a' "$WORK")

echo "[1/8] Extracting native base ISO"
xorriso -osirrox on -indev "$BASE_ISO" -extract / "$ISO_ROOT"

echo "[2/8] Unpacking native live filesystem: $ROOTFS_REL"
[[ -f "$ISO_ROOT/$ROOTFS_REL" ]] || { echo "Live rootfs not found: $ISO_ROOT/$ROOTFS_REL" >&2; exit 3; }
sudo unsquashfs -f -d "$ROOTFS" "$ISO_ROOT/$ROOTFS_REL"
ORIG_SQUASH_BYTES=$(stat -Lc '%s' "$ISO_ROOT/$ROOTFS_REL")
ORIG_ROOT_BYTES=$(sudo du -sx --block-size=1 "$ROOTFS" | awk '{print $1}')
[[ "$ORIG_ROOT_BYTES" =~ ^[0-9]+$ && "$ORIG_ROOT_BYTES" -gt 0 ]] || { echo "Could not measure unpacked rootfs size" >&2; exit 5; }

# Fail early on an obviously undersized work filesystem instead of surfacing a
# misleading mksquashfs/xorriso write error much later. Measured after the
# expanded rootfs already exists; the remaining budget mainly covers package
# growth plus a complete output ISO.
FREE_BYTES=$(df -PB1 "$WORK" | awk 'NR==2 {print $4}')
BASE_BYTES=$(stat -Lc '%s' "$BASE_ISO")
MIN_FREE=$((BASE_BYTES + 3 * 1024 * 1024 * 1024))
WARN_FREE=$((BASE_BYTES + 8 * 1024 * 1024 * 1024))
if (( FREE_BYTES < MIN_FREE )); then
  echo "Insufficient free space for Native remaster: ${FREE_BYTES} bytes free; need at least ${MIN_FREE}." >&2
  exit 5
elif (( FREE_BYTES < WARN_FREE )); then
  echo "warning: Native work filesystem has limited headroom (${FREE_BYTES} bytes free)." >&2
fi

echo "[3/8] Injecting Suret profile and pre-login convergence"
sudo mkdir -p "$ROOTFS/usr/share/linux-iso/profile" "$ROOTFS/usr/lib/linux-iso" "$ROOTFS/etc/xdg/autostart"
sudo rsync -a --delete "$PROFILE/" "$ROOTFS/usr/share/linux-iso/profile/"
sudo install -m 0755 "$HERE/native-first-login.py" "$ROOTFS/usr/lib/linux-iso/native-first-login.py"
sudo install -m 0755 "$HERE/native-prelogin.py" "$ROOTFS/usr/lib/linux-iso/native-prelogin.py"
sudo install -m 0755 "$HERE/native-system-visual.py" "$ROOTFS/usr/lib/linux-iso/native-system-visual.py"
sudo install -m 0755 "$HERE/native-vendor-archive.py" "$ROOTFS/usr/lib/linux-iso/native-vendor-archive.py"
sudo install -m 0644 "$HERE/linux-iso-native-first-login.desktop" "$ROOTFS/etc/xdg/autostart/linux-iso-native-first-login.desktop"
sudo install -m 0644 "$HERE/linux-iso-native-prelogin.service" "$ROOTFS/etc/systemd/system/linux-iso-native-prelogin.service"
sudo mkdir -p "$ROOTFS/etc/systemd/system/graphical.target.wants"
sudo ln -sfn /etc/systemd/system/linux-iso-native-prelogin.service "$ROOTFS/etc/systemd/system/graphical.target.wants/linux-iso-native-prelogin.service"

for path in dev proc sys run; do sudo mkdir -p "$ROOTFS/$path"; done
# Make the chroot root a mount point of its own. Flatpak/bubblewrap performs
# recursive mount-propagation changes on / while deploying extra-data apps; a
# plain chroot directory makes that fail with "Failed to make / slave: EINVAL".
# A self bind is disposable and is detached by cleanup_mounts().
sudo mount --bind "$ROOTFS" "$ROOTFS"
# Bind-mount VFS flags are independent from the parent mount. Temporarily allow
# setuid only on this disposable chroot mount so bubblewrap's documented
# fallback can work even when /home itself is mounted nosuid. The bind mount is
# detached before the work tree is exposed again.
sudo mount -o remount,bind,suid "$ROOTFS"
sudo mount --make-rslave "$ROOTFS"
# /dev needs its child mounts (notably /dev/pts). /run must NOT expose the host
# systemd/dbus sockets to package maintainer scripts inside the chroot.
sudo mount --rbind /dev "$ROOTFS/dev"
sudo mount --make-rslave "$ROOTFS/dev"
sudo mount -t proc proc "$ROOTFS/proc"
# A fresh read-only sysfs view is enough for package detection and prevents
# chroot maintainer scripts from writing into host sysfs.
sudo mount -t sysfs -o ro,nosuid,nodev,noexec sysfs "$ROOTFS/sys"
# /run is an isolated ephemeral build tmpfs and remains nosuid; the temporary
# bubblewrap setuid fallback lives on the sealed ROOTFS bind mount, not /run.
sudo mount -t tmpfs -o mode=0755,nosuid,nodev tmpfs "$ROOTFS/run"
sudo mkdir -p "$ROOTFS/run/lock"
# Do not let the target image's package/Flatpak resolution inspect the build
# host's loaded GPU/kernel modules. This avoids pulling driver-version-specific
# Flatpak extensions (for example NVIDIA) into a portable ISO.
sudo mkdir -p "$ROOTFS/run/linux-iso-hw-mask/sys-module"
sudo install -m 0644 /dev/null "$ROOTFS/run/linux-iso-hw-mask/proc-modules"
sudo mount --bind "$ROOTFS/run/linux-iso-hw-mask/proc-modules" "$ROOTFS/proc/modules"
sudo mount --bind "$ROOTFS/run/linux-iso-hw-mask/sys-module" "$ROOTFS/sys/module"
sudo cp -a "$ROOTFS/etc/resolv.conf" "$ROOTFS/etc/resolv.conf.suret-backup" 2>/dev/null || true
sudo rm -f "$ROOTFS/etc/resolv.conf"
sudo cp -L /etc/resolv.conf "$ROOTFS/etc/resolv.conf"

echo "[4/8] Installing target desktop and source applications inside native distro"
sudo cp "$HERE/native-install.sh" "$ROOTFS/tmp/linux-iso-native-install.sh"
sudo chmod 0755 "$ROOTFS/tmp/linux-iso-native-install.sh"
# A temporary setuid bubblewrap fallback may be needed by Flatpak extra-data.
# Hide the entire disposable work tree from the invoking user during that
# window; on any ordinary failure we sanitize privileges before reopening it.
seal_work_tree
set +e
sudo chroot "$ROOTFS" /usr/bin/env REPLACE_DESKTOP="$REPLACE_DESKTOP" /bin/bash /tmp/linux-iso-native-install.sh
CHROOT_INSTALL_RC=$?
set -e
sanitize_build_privileges
unseal_work_tree
if (( CHROOT_INSTALL_RC != 0 )); then
  exit "$CHROOT_INSTALL_RC"
fi

# Never allow the build-only fallback to leak into the finished ISO.
for bwrap_path in "$ROOTFS/usr/bin/bwrap" "$ROOTFS/usr/libexec/flatpak-bwrap"; do
  if [[ -e "$bwrap_path" && -u "$bwrap_path" ]]; then
    echo "Native Flatpak bootstrap left a setuid bubblewrap helper behind: $bwrap_path" >&2
    exit 34
  fi
done

# Apply system-visible fonts/cursor/SDDM state after KDE/SDDM packages exist.
if ! sudo chroot "$ROOTFS" /usr/lib/linux-iso/native-system-visual.py; then
  echo "Native system visual convergence failed; refusing to ship a visually divergent ISO." >&2
  exit 35
fi

cleanup_chroot
# cleanup helpers run in subshells, so the parent retains `set -e`; all critical
# metadata/repack failures below remain fatal.

# Re-estimate the remaining space after package/application growth. The old
# squashfs will be deleted before the new one is written, so count that space
# as reclaimable. Estimate compressed size from the base image's observed
# compression ratio, add 25% safety margin + 512 MiB, then reserve another
# full output ISO plus 1 GiB working margin for xorriso.
NEW_ROOT_BYTES=$(sudo du -sx --block-size=1 "$ROOTFS" | awk '{print $1}')
FREE_BYTES=$(df -PB1 "$WORK" | awk 'NR==2 {print $4}')
EST_SQUASH_BYTES=$(( NEW_ROOT_BYTES * ORIG_SQUASH_BYTES / ORIG_ROOT_BYTES ))
EST_SQUASH_BYTES=$(( EST_SQUASH_BYTES + EST_SQUASH_BYTES / 4 + 512 * 1024 * 1024 ))
EST_ISO_BYTES=$(( BASE_BYTES - ORIG_SQUASH_BYTES + EST_SQUASH_BYTES ))
AVAILABLE_AFTER_OLD_SQUASH_REMOVAL=$(( FREE_BYTES + ORIG_SQUASH_BYTES ))
REQUIRED_REPACK_BYTES=$(( EST_SQUASH_BYTES + EST_ISO_BYTES + 1024 * 1024 * 1024 ))
if (( AVAILABLE_AFTER_OLD_SQUASH_REMOVAL < REQUIRED_REPACK_BYTES )); then
  echo "Insufficient free space after Native package growth." >&2
  echo "Estimated repack requirement: $REQUIRED_REPACK_BYTES bytes; available after replacing old squashfs: $AVAILABLE_AFTER_OLD_SQUASH_REMOVAL bytes." >&2
  exit 5
fi
echo "Native repack space estimate: need ~$REQUIRED_REPACK_BYTES bytes; available ~$AVAILABLE_AFTER_OLD_SQUASH_REMOVAL bytes"

echo "[5/8] Refreshing live metadata"
sudo mkdir -p "$ISO_ROOT/$LIVE_DIR"
if [[ -x "$ROOTFS/usr/bin/dpkg-query" ]]; then
  sudo chroot "$ROOTFS" dpkg-query -W -f='${Package} ${Version}\n' | sudo tee "$ISO_ROOT/$LIVE_DIR/filesystem.packages" >/dev/null
  [[ -s "$ISO_ROOT/$LIVE_DIR/filesystem.packages" ]] || { echo "Generated filesystem.packages is empty" >&2; exit 4; }
fi
# Debian-live/Pardus installers use filesystem.size for target-space checks.
sudo du -sx --block-size=1 "$ROOTFS" | awk '{print $1}' | sudo tee "$ISO_ROOT/$LIVE_DIR/filesystem.size" >/dev/null

SQ_INFO=$(unsquashfs -s "$ISO_ROOT/$ROOTFS_REL" 2>/dev/null)
COMP=$(awk 'tolower($1) ~ /^compression:?$/ {print $2; exit}' <<<"$SQ_INFO")
BLOCK_SIZE=$(awk 'tolower($1) == "block" && tolower($2) == "size" {print $3; exit}' <<<"$SQ_INFO")
[[ -n "$COMP" ]] || COMP=xz
MKSQ_ARGS=(-noappend -comp "$COMP")
if [[ "$BLOCK_SIZE" =~ ^[0-9]+$ ]]; then
  MKSQ_ARGS+=( -b "$BLOCK_SIZE" )
fi
echo "Repacking live filesystem with compression: $COMP, block size: ${BLOCK_SIZE:-default}"
sudo rm -f "$ISO_ROOT/$ROOTFS_REL"
sudo mksquashfs "$ROOTFS" "$ISO_ROOT/$ROOTFS_REL" "${MKSQ_ARGS[@]}"
unsquashfs -s "$ISO_ROOT/$ROOTFS_REL" >/dev/null || { echo "Rebuilt SquashFS failed structural validation" >&2; exit 4; }

if [[ -f "$ISO_ROOT/md5sum.txt" ]]; then
  echo "[6/8] Regenerating ISO checksums"
  (cd "$ISO_ROOT" && find . -type f ! -name md5sum.txt ! -path './isolinux/boot.cat' -print0 | sort -z | xargs -0 md5sum) | sudo tee "$ISO_ROOT/md5sum.txt" >/dev/null
else
  echo "[6/8] No md5sum.txt in base ISO; preserving native metadata"
fi

echo "[7/8] Replaying native boot catalog and writing ISO"
rm -f "$TMP_ISO"

CURRENT_BASE_STAMP=$(stat -Lc '%d:%i:%s:%Y' "$BASE_ISO")
[[ "$CURRENT_BASE_STAMP" == "$BASE_STAMP" ]] || {
  echo "Base ISO changed while the Native build was running; refusing a mixed-source remaster." >&2
  exit 4
}

# xorriso 1.5.6 has a known replay bug if the legacy BIOS boot image is
# replaced by -map before `-boot_image any replay`. Do not remap the complete
# extracted tree: preserve boot files directly from the loaded base ISO and
# replace only artifacts that Suret actually changed. The result is first
# written to a .partial path and becomes the public ISO only after verification.
XORRISO_ARGS=(
  -indev "$BASE_ISO"
  -outdev "$TMP_ISO"
  -map "$ISO_ROOT/$ROOTFS_REL" "/$ROOTFS_REL"
  -map "$ISO_ROOT/$LIVE_DIR/filesystem.size" "/$LIVE_DIR/filesystem.size"
)
if [[ -f "$ISO_ROOT/$LIVE_DIR/filesystem.packages" ]]; then
  XORRISO_ARGS+=( -map "$ISO_ROOT/$LIVE_DIR/filesystem.packages" "/$LIVE_DIR/filesystem.packages" )
fi
if [[ -f "$ISO_ROOT/md5sum.txt" ]]; then
  XORRISO_ARGS+=( -map "$ISO_ROOT/md5sum.txt" /md5sum.txt )
fi
XORRISO_ARGS+=( -boot_image any replay -commit )
xorriso "${XORRISO_ARGS[@]}"

echo "[8/8] Verifying remastered ISO structure and boot metadata"
[[ -s "$TMP_ISO" ]] || { echo "Native ISO was not created: $TMP_ISO" >&2; exit 4; }
# xorriso -find uses action `echo` by default; use it explicitly for 1.5.6
# compatibility. Shell-find's `-print` is not a valid xorriso -find option.
VERIFY=$(xorriso -indev "$TMP_ISO" -find "/$ROOTFS_REL" -type f -exec echo -- 2>/dev/null || true)
grep -Fq "/$ROOTFS_REL" <<<"$VERIFY" || { echo "Remastered ISO is missing /$ROOTFS_REL" >&2; exit 4; }

if ! BASE_BOOT_REPORT=$(xorriso -indev "$BASE_ISO" -report_el_torito plain -report_system_area plain 2>&1); then
  echo "Could not read boot metadata from base ISO." >&2
  printf '%s\n' "$BASE_BOOT_REPORT" >&2
  exit 4
fi
if ! OUT_BOOT_REPORT=$(xorriso -indev "$TMP_ISO" -report_el_torito plain -report_system_area plain 2>&1); then
  echo "Could not read boot metadata from remastered ISO." >&2
  printf '%s\n' "$OUT_BOOT_REPORT" >&2
  exit 4
fi
{
  echo "===== BASE ISO BOOT REPORT ====="
  printf '%s\n' "$BASE_BOOT_REPORT"
  echo "===== REMASTERED ISO BOOT REPORT ====="
  printf '%s\n' "$OUT_BOOT_REPORT"
} > "$RESULT/native-boot-report.txt"
for platform in BIOS UEFI; do
  if grep -Eq "El Torito boot img :.*[[:space:]]${platform}[[:space:]]" <<<"$BASE_BOOT_REPORT"; then
    grep -Eq "El Torito boot img :.*[[:space:]]${platform}[[:space:]]" <<<"$OUT_BOOT_REPORT" || {
      echo "Remastered ISO lost the base ISO's $platform El Torito boot entry." >&2
      exit 4
    }
  fi
done
for table in MBR GPT APM; do
  if grep -Eq "Boot record[[:space:]]*:.*[ ,]${table}([ ,]|$)" <<<"$BASE_BOOT_REPORT"; then
    grep -Eq "Boot record[[:space:]]*:.*[ ,]${table}([ ,]|$)" <<<"$OUT_BOOT_REPORT" || {
      echo "Remastered ISO lost the base ISO's $table boot/system-area metadata." >&2
      exit 4
    }
  fi
done

mv -f -- "$TMP_ISO" "$OUT_ISO"
OUT_SHA256=$(sha256sum "$OUT_ISO" | awk '{print $1}')
printf '%s  %s\n' "$OUT_SHA256" "${OUT_ISO##*/}" > "$OUT_ISO.sha256"
BUILD_FINISHED=1
if [[ "${LINUX_ISO_KEEP_NATIVE_WORK:-0}" != "1" ]]; then
  cleanup_mounts
  sudo rm -rf --one-file-system -- "$WORK" || echo "warning: could not remove successful Native work tree: $WORK" >&2
else
  echo "Keeping Native work tree by request: $WORK"
fi
echo "Native ISO ready: $OUT_ISO"
echo "SHA-256: $OUT_ISO.sha256"
echo "Boot verification report: $RESULT/native-boot-report.txt"
echo "This image retains the base distro's bootloader, installer, repositories and OS identity."
'''

NATIVE_INSTALL_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
# Build-time locale must be guaranteed to exist inside the base live rootfs.
# Do not inherit the source host's mixed tr_TR/en_US locale into maintainer
# scripts; final user locale is restored by the captured profile separately.
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export LANGUAGE=
DISTRO_ID=__DISTRO_ID__

log() { printf '[native] %s\n' "$*"; }

# Never let package maintainer scripts start services against the build host.
# The build uses an isolated /run too, but policy-rc.d is the Debian-family
# contract for suppressing service starts during image construction.
POLICY=/usr/sbin/policy-rc.d
POLICY_BACKUP=/usr/sbin/policy-rc.d.suret-backup
BWRAP_BUILD_PATH=""
BWRAP_BUILD_MODE=""
restore_policy() {
  rm -f "$POLICY"
  if [[ -e "$POLICY_BACKUP" || -L "$POLICY_BACKUP" ]]; then
    mv "$POLICY_BACKUP" "$POLICY"
  fi
}
restore_build_bwrap() {
  if [[ -n "$BWRAP_BUILD_PATH" && -n "$BWRAP_BUILD_MODE" && -e "$BWRAP_BUILD_PATH" ]]; then
    chmod "$BWRAP_BUILD_MODE" "$BWRAP_BUILD_PATH" || true
  fi
  unset FLATPAK_BWRAP || true
}
cleanup_native_install() {
  restore_build_bwrap
  restore_policy
}
trap cleanup_native_install EXIT
if [[ -e "$POLICY" || -L "$POLICY" ]]; then
  mv "$POLICY" "$POLICY_BACKUP"
fi
cat > "$POLICY" <<'EOS'
#!/bin/sh
exit 101
EOS
chmod 0755 "$POLICY"

# The live rootfs may intentionally carry a file:/run/live/medium or cdrom:
# source for the live session/installer. Inside the remaster chroot that source
# is not a package repository and makes `apt-get update` exit 100 even when all
# network indexes were fetched successfully. Never rewrite the distro's final
# APT configuration just to build the image. Instead use an isolated,
# build-only source list and package-index state under the tmpfs /run.
APT_RUNTIME_ROOT=${SURET_APT_RUNTIME_ROOT:-/run/linux-iso}
APT_BUILD_SOURCES=""
APT_CONFIG_OPTS=()

configure_native_build_apt() {
  [[ "$DISTRO_ID" == "pardus" ]] || return 0

  local apt_root="$APT_RUNTIME_ROOT/apt-build"
  local sourceparts="$apt_root/sourceparts"
  local lists="$apt_root/lists"
  APT_BUILD_SOURCES="$apt_root/sources.list"
  mkdir -p "$sourceparts" "$lists/partial"

  cat > "$APT_BUILD_SOURCES" <<'EOS'
deb http://depo.pardus.org.tr/pardus yirmibes main contrib non-free non-free-firmware
deb http://depo.pardus.org.tr/pardus yirmibes-deb main contrib non-free non-free-firmware
deb http://depo.pardus.org.tr/guvenlik yirmibes-deb main contrib non-free non-free-firmware
EOS

  APT_CONFIG_OPTS=(
    -o "Dir::Etc::sourcelist=$APT_BUILD_SOURCES"
    -o "Dir::Etc::sourceparts=$sourceparts"
    -o "Dir::State::lists=$lists"
    -o "Acquire::Languages=none"
    -o "Acquire::IndexTargets::deb::Contents-deb::DefaultEnabled=false"
    -o "Acquire::IndexTargets::deb::Contents-udeb::DefaultEnabled=false"
  )
  log "Using isolated official Pardus 25 APT sources for the chroot build"
  log "Preserving the live ISO's original local-media/package-source configuration"
}

vendor_archive_apps=(__VENDOR_ARCHIVE_APPS__)
flatpaks=(__FLATPAKS__)

if command -v apt-get >/dev/null 2>&1; then
  configure_native_build_apt
  APT_GET=(apt-get "${APT_CONFIG_OPTS[@]}" -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
  APT_CACHE=(apt-cache "${APT_CONFIG_OPTS[@]}")
  log "Refreshing native APT metadata"
  "${APT_GET[@]}" update

  required_desktop_pkgs=(__REQUIRED_DESKTOP_PACKAGES__)
  optional_desktop_pkgs=(__OPTIONAL_DESKTOP_PACKAGES__)
  missing_required=()
  for pkg in "${required_desktop_pkgs[@]}"; do
    "${APT_CACHE[@]}" show "$pkg" >/dev/null 2>&1 || missing_required+=("$pkg")
  done
  if (( ${#missing_required[@]} > 0 )); then
    log "ERROR: native repository is missing required KDE packages: ${missing_required[*]}"
    exit 21
  fi

  if (( ${#required_desktop_pkgs[@]} > 0 )); then
    log "Installing required KDE/Plasma packages into the native distro"
    "${APT_GET[@]}" install -y --no-install-recommends "${required_desktop_pkgs[@]}"
  fi

  appearance_pkgs=(__APPEARANCE_PACKAGES__)
  missing_appearance=()
  for pkg in "${appearance_pkgs[@]}"; do
    "${APT_CACHE[@]}" show "$pkg" >/dev/null 2>&1 || missing_appearance+=("$pkg")
  done
  if (( ${#missing_appearance[@]} > 0 )); then
    log "ERROR: source appearance package(s) are unavailable in the native target repositories: ${missing_appearance[*]}"
    log "Refusing to build an ISO that would silently lose captured themes/widgets/fonts."
    exit 24
  fi
  if (( ${#appearance_pkgs[@]} > 0 )); then
    log "Installing ${#appearance_pkgs[@]} source appearance package(s) required for fidelity"
    "${APT_GET[@]}" install -y "${appearance_pkgs[@]}"
    for pkg in "${appearance_pkgs[@]}"; do
      dpkg-query -W -f='${db:Status-Abbrev}' "$pkg" 2>/dev/null | grep -q '^ii' || {
        log "ERROR: required appearance package was not installed successfully: $pkg"
        exit 25
      }
    done
  fi

  log "Installing optional desktop integration packages when available"
  for pkg in "${optional_desktop_pkgs[@]}"; do
    if "${APT_CACHE[@]}" show "$pkg" >/dev/null 2>&1; then
      "${APT_GET[@]}" install -y --no-install-recommends "$pkg" || log "warning: could not install optional $pkg"
    else
      log "warning: native repository does not provide optional $pkg"
    fi
  done

  if (( ${#flatpaks[@]} > 0 )); then
    log "Profile contains true Flatpak applications; installing Flatpak runtime support from Pardus"
    for pkg in flatpak bubblewrap; do
      if ! "${APT_CACHE[@]}" show "$pkg" >/dev/null 2>&1; then
        log "ERROR: required Flatpak runtime package is unavailable in Pardus repositories: $pkg"
        exit 46
      fi
    done
    "${APT_GET[@]}" install -y --no-install-recommends flatpak bubblewrap
  fi

  command -v plasmashell >/dev/null 2>&1 || { log "ERROR: KDE installation completed without plasmashell"; exit 22; }
  [[ -f /usr/share/wayland-sessions/plasma.desktop || -f /usr/share/xsessions/plasma.desktop || -f /usr/share/xsessions/plasmax11.desktop ]] || {
    log "ERROR: KDE installation did not create a Plasma session desktop file"
    exit 23
  }

  if [[ "${REPLACE_DESKTOP:-0}" == "1" ]]; then
    remove_pkgs=(__REMOVE_PACKAGES__)
    log "Removing the base desktop session while keeping the native distro"
    "${APT_GET[@]}" purge -y "${remove_pkgs[@]}" || true
    "${APT_GET[@]}" autoremove -y || true
  fi

  native_apps=(__NATIVE_APPS__)
  log "Installing captured native applications from the same distro repositories"
  for pkg in "${native_apps[@]}"; do
    if ! "${APT_CACHE[@]}" show "$pkg" >/dev/null 2>&1; then
      log "ERROR: captured native application is unavailable in the target repositories: $pkg"
      exit 32
    fi
    if ! "${APT_GET[@]}" install -y "$pkg"; then
      log "ERROR: captured native application failed to install: $pkg"
      exit 33
    fi
  done

  vendor_apt_apps=(__VENDOR_APT_APPS__)
  if (( ${#vendor_apt_apps[@]} > 0 )); then
    log "Installing captured vendor APT applications from vetted official repositories"

    # Repository metadata below is compiled into Suret. The profile contributes
    # only a resolver ID selected from this allow-list; it cannot inject URLs,
    # key paths or shell fragments. Keep the vendor source in the final image so
    # the installed application receives normal upstream APT updates.
    vendor_bootstrap_pkgs=(ca-certificates curl gpg)
    for pkg in "${vendor_bootstrap_pkgs[@]}"; do
      if ! "${APT_CACHE[@]}" show "$pkg" >/dev/null 2>&1; then
        log "ERROR: native repository lacks vendor-repository bootstrap package: $pkg"
        exit 39
      fi
    done
    "${APT_GET[@]}" install -y --no-install-recommends "${vendor_bootstrap_pkgs[@]}"
    export GNUPGHOME="$APT_RUNTIME_ROOT/vendor-gnupg"
    mkdir -p "$GNUPGHOME"
    chmod 0700 "$GNUPGHOME"

    for vendor in "${vendor_apt_apps[@]}"; do
      key_format="dearmor"
      source_url=""
      case "$vendor" in
        brave-browser)
          vendor_name="Brave Browser"
          vendor_pkg="brave-browser"
          key_url="https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg"
          keyring="/usr/share/keyrings/brave-browser-archive-keyring.gpg"
          source_file="/etc/apt/sources.list.d/brave-browser-release.sources"
          source_url="https://brave-browser-apt-release.s3.brave.com/brave-browser.sources"
          source_line="deb [arch=amd64 signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com stable main"
          key_format="raw"
          ;;
        microsoft-vscode)
          vendor_name="Visual Studio Code"
          vendor_pkg="code"
          key_url="https://packages.microsoft.com/keys/microsoft.asc"
          keyring="/usr/share/keyrings/microsoft-vscode.gpg"
          source_file="/etc/apt/sources.list.d/vscode.list"
          source_line="deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-vscode.gpg] https://packages.microsoft.com/repos/code stable main"
          ;;
        signal-desktop)
          vendor_name="Signal Desktop"
          vendor_pkg="signal-desktop"
          key_url="https://updates.signal.org/desktop/apt/keys.asc"
          keyring="/usr/share/keyrings/signal-desktop-keyring.gpg"
          source_file="/etc/apt/sources.list.d/signal-desktop.list"
          source_line="deb [arch=amd64 signed-by=/usr/share/keyrings/signal-desktop-keyring.gpg] https://updates.signal.org/desktop/apt xenial main"
          ;;
        *)
          log "ERROR: unknown vendor APT resolver reached generated build script: $vendor"
          exit 40
          ;;
      esac

      log "Adding official vendor repository for $vendor_name"
      key_tmp="$APT_RUNTIME_ROOT/vendor-${vendor}.key"
      mkdir -p "$(dirname "$keyring")" "$(dirname "$source_file")"
      if ! curl --fail --silent --show-error --location --retry 3 --connect-timeout 20 --max-time 120 "$key_url" -o "$key_tmp"; then
        log "ERROR: could not download signing key for $vendor_name"
        exit 41
      fi
      if [[ "$key_format" == "raw" ]]; then
        if ! gpg --batch --show-keys "$key_tmp" >/dev/null 2>&1; then
          log "ERROR: downloaded vendor signing key is not a valid OpenPGP key for $vendor_name"
          exit 42
        fi
        install -m 0644 "$key_tmp" "$keyring"
      else
        if ! gpg --batch --yes --dearmor --output "$keyring" "$key_tmp"; then
          log "ERROR: could not prepare signing key for $vendor_name"
          exit 42
        fi
        chmod 0644 "$keyring"
      fi
      if [[ -n "$source_url" ]]; then
        if ! curl --fail --silent --show-error --location --retry 3 --connect-timeout 20 --max-time 120 "$source_url" -o "$source_file"; then
          log "ERROR: could not download official APT source descriptor for $vendor_name"
          exit 41
        fi
        chmod 0644 "$source_file"
      else
        printf '%s\n' "$source_line" > "$source_file"
        chmod 0644 "$source_file"
      fi
      # Native builds use an isolated source list, so mirror the vetted source
      # as a one-line entry there while preserving the vendor's official .sources
      # descriptor in the installed image for normal future updates.
      if ! grep -Fqx -- "$source_line" "$APT_BUILD_SOURCES"; then
        printf '%s\n' "$source_line" >> "$APT_BUILD_SOURCES"
      fi
    done

    log "Refreshing APT metadata with selected official vendor repositories"
    "${APT_GET[@]}" update

    for vendor in "${vendor_apt_apps[@]}"; do
      case "$vendor" in
        brave-browser) vendor_name="Brave Browser"; vendor_pkg="brave-browser" ;;
        microsoft-vscode) vendor_name="Visual Studio Code"; vendor_pkg="code" ;;
        signal-desktop) vendor_name="Signal Desktop"; vendor_pkg="signal-desktop" ;;
        *) log "ERROR: unknown vendor APT resolver during install: $vendor"; exit 40 ;;
      esac
      if ! "${APT_CACHE[@]}" show "$vendor_pkg" >/dev/null 2>&1; then
        log "ERROR: official vendor repository does not provide required package: $vendor_pkg"
        exit 43
      fi
      if ! "${APT_GET[@]}" install -y "$vendor_pkg"; then
        log "ERROR: official vendor package failed to install: $vendor_pkg"
        exit 44
      fi
      if ! dpkg-query -W -f='${db:Status-Abbrev}' "$vendor_pkg" 2>/dev/null | grep -q '^ii'; then
        log "ERROR: vendor package install returned without a configured package: $vendor_pkg"
        exit 45
      fi
      log "Verified vendor-native application: $vendor_name ($vendor_pkg)"
    done
  fi

  if command -v debconf-set-selections >/dev/null 2>&1 && "${APT_CACHE[@]}" show sddm >/dev/null 2>&1; then
    printf 'sddm shared/default-x-display-manager select sddm\n' | debconf-set-selections || true
  fi
  if [[ -e /lib/systemd/system/sddm.service || -e /usr/lib/systemd/system/sddm.service ]]; then
    mkdir -p /etc/systemd/system /etc/sddm.conf.d /etc/systemd/system/sddm.service.d
    if [[ -e /lib/systemd/system/sddm.service ]]; then
      ln -sfn /lib/systemd/system/sddm.service /etc/systemd/system/display-manager.service
    else
      ln -sfn /usr/lib/systemd/system/sddm.service /etc/systemd/system/display-manager.service
    fi
    cat > /usr/lib/linux-iso/sddm-live-prepare <<'EOS'
#!/bin/sh
set -eu
if grep -qw 'boot=live' /proc/cmdline || [ -d /run/live/medium ]; then
    # live-config may create the account after graphical.target starts; retry
    # Suret's pre-login copy at the last safe point before SDDM paints.
    /usr/lib/linux-iso/native-prelogin.py || true
    user=""
    if [ -s /run/linux-iso/target-user ]; then
        user=$(cat /run/linux-iso/target-user 2>/dev/null || true)
    fi
    if [ -z "$user" ]; then
        user=$(awk -F: '$3 >= 1000 && $3 < 60000 && $6 ~ /^\/home\// && $7 !~ /(nologin|false)$/ { if (min == "" || $3 < min) { min=$3; name=$1 } } END { print name }' /etc/passwd || true)
    fi
    [ -n "$user" ] || exit 0
    session=plasma
    if [ -f /usr/share/wayland-sessions/plasma.desktop ]; then
        session=plasma
    elif [ -f /usr/share/xsessions/plasmax11.desktop ]; then
        session=plasmax11
    elif [ -f /usr/share/xsessions/plasma.desktop ]; then
        session=plasma
    fi
    cat > /etc/sddm.conf.d/99-suret-live.conf <<EOC
[Autologin]
User=$user
Session=$session
Relogin=true
EOC
else
    rm -f /etc/sddm.conf.d/99-suret-live.conf
fi
EOS
    chmod 0755 /usr/lib/linux-iso/sddm-live-prepare
    cat > /etc/systemd/system/sddm.service.d/20-suret-live.conf <<'EOS'
[Service]
ExecStartPre=/usr/lib/linux-iso/sddm-live-prepare
EOS
  fi
  update-initramfs -u -k all || true
  "${APT_GET[@]}" clean
fi

if (( ${#vendor_archive_apps[@]} > 0 )); then
  log "Installing captured extra-data applications from vetted official vendor archives"
  archive_bootstrap_pkgs=(ca-certificates curl python3 tar)
  if declare -p APT_GET >/dev/null 2>&1; then
    for pkg in "${archive_bootstrap_pkgs[@]}"; do
      if ! "${APT_CACHE[@]}" show "$pkg" >/dev/null 2>&1; then
        log "ERROR: native repository lacks vendor-archive bootstrap package: $pkg"
        exit 46
      fi
    done
    "${APT_GET[@]}" install -y --no-install-recommends "${archive_bootstrap_pkgs[@]}"
  fi

  for vendor in "${vendor_archive_apps[@]}"; do
    case "$vendor" in
      google-android-studio)
        vendor_name="Android Studio"
        metadata_url="https://developer.android.com/studio?hl=en&pkg=studio"
        vendor_tmp="/var/tmp/linux-iso-vendor/android-studio"
        page="$vendor_tmp/download.html"
        meta="$vendor_tmp/download.tsv"
        mkdir -p "$vendor_tmp" /usr/local/bin
        log "Resolving current stable $vendor_name Linux archive from Android Developers"
        if ! curl --fail --silent --show-error --location --retry 4 --retry-delay 2 --connect-timeout 30 \
          --user-agent 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Suret-Native/1.0' \
          "$metadata_url" -o "$page"; then
          log "ERROR: could not load official Android Studio download metadata"
          exit 47
        fi
        if ! /usr/lib/linux-iso/native-vendor-archive.py parse-android-metadata "$page" "$meta"; then
          log "ERROR: official Android Studio metadata could not be parsed safely"
          exit 48
        fi
        IFS=$'\t' read -r archive_url archive_sha archive_name < "$meta"
        if [[ ! "$archive_sha" =~ ^[0-9a-f]{64}$ || "$archive_name" != android-studio-*-linux.tar.gz ]]; then
          log "ERROR: resolved Android Studio metadata failed validation"
          exit 49
        fi
        archive="$vendor_tmp/$archive_name"
        partial="$archive.part"
        cached_ok=0
        if [[ -f "$archive" ]]; then
          actual_sha=$(sha256sum "$archive" | awk '{print $1}')
          [[ "$actual_sha" == "$archive_sha" ]] && cached_ok=1
        fi
        if (( cached_ok == 0 )); then
          rm -f -- "$archive"
          log "Downloading $vendor_name vendor archive: $archive_name"
          if ! curl --fail --show-error --location --retry 5 --retry-delay 3 --connect-timeout 30 \
            --continue-at - "$archive_url" -o "$partial"; then
            log "ERROR: official Android Studio archive download failed"
            exit 50
          fi
          actual_sha=$(sha256sum "$partial" | awk '{print $1}')
          if [[ "$actual_sha" != "$archive_sha" ]]; then
            rm -f -- "$partial"
            log "ERROR: Android Studio SHA-256 mismatch"
            exit 51
          fi
          mv -f -- "$partial" "$archive"
        else
          log "Reusing verified Android Studio archive: $archive_name"
        fi
        rm -rf -- /opt/android-studio
        if ! /usr/lib/linux-iso/native-vendor-archive.py extract-android "$archive" /opt; then
          log "ERROR: Android Studio archive failed safe extraction"
          exit 52
        fi
        studio_exec=""
        for candidate in /opt/android-studio/bin/studio /opt/android-studio/bin/studio.sh; do
          if [[ -f "$candidate" ]]; then studio_exec="$candidate"; break; fi
        done
        if [[ -z "$studio_exec" ]]; then
          log "ERROR: Android Studio archive did not contain a launch executable"
          exit 53
        fi
        chmod 0755 "$studio_exec"
        ln -sfn "$studio_exec" /usr/local/bin/android-studio
        mkdir -p /usr/share/applications /usr/share/icons/hicolor/scalable/apps /usr/share/linux-iso/vendor
        icon_source=""
        for candidate in /opt/android-studio/bin/studio.svg /opt/android-studio/bin/android-studio.svg; do
          if [[ -f "$candidate" ]]; then icon_source="$candidate"; break; fi
        done
        if [[ -n "$icon_source" ]]; then
          cp -f -- "$icon_source" /usr/share/icons/hicolor/scalable/apps/android-studio.svg
          cp -f -- "$icon_source" /usr/share/icons/hicolor/scalable/apps/com.google.AndroidStudio.svg
        fi
        cat > /usr/share/applications/com.google.AndroidStudio.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Android Studio
Comment=The official IDE for Android development
Exec=$studio_exec %f
TryExec=$studio_exec
Icon=android-studio
Terminal=false
Categories=Development;IDE;
StartupWMClass=jetbrains-android-studio
EOF
        ln -sfn com.google.AndroidStudio.desktop /usr/share/applications/android-studio.desktop
        printf 'source_url=%s\nsha256=%s\narchive=%s\n' "$archive_url" "$archive_sha" "$archive_name" \
          > /usr/share/linux-iso/vendor/google-android-studio.txt
        chmod 0644 /usr/share/applications/com.google.AndroidStudio.desktop /usr/share/linux-iso/vendor/google-android-studio.txt
        if [[ ! -x "$studio_exec" || ! -f /usr/share/applications/com.google.AndroidStudio.desktop ]]; then
          log "ERROR: Android Studio vendor archive verification failed"
          exit 54
        fi
        rm -rf -- "$vendor_tmp"
        log "Verified vendor-native application: Android Studio ($studio_exec)"
        ;;
      *)
        log "ERROR: unknown vendor archive resolver reached generated build script: $vendor"
        exit 55
        ;;
    esac
  done
fi

if (( ${#flatpaks[@]} > 0 )); then
  if ! command -v flatpak >/dev/null 2>&1; then
    log "ERROR: captured Flatpak applications exist but flatpak is not installed"
    exit 30
  fi
  if ! command -v bwrap >/dev/null 2>&1; then
    log "ERROR: Flatpak is installed but bubblewrap is unavailable"
    exit 34
  fi

  # Make one last distro-native upgrade attempt before entering Flatpak's
  # sandbox path. Flatpak 1.16.5 had upstream /proc/self/fd regressions that
  # were fixed in 1.16.6; never add Debian/Ubuntu repositories to work around
  # a lagging Pardus package, but do consume a newer candidate if Pardus ships it.
  if declare -p APT_GET >/dev/null 2>&1; then
    "${APT_GET[@]}" install -y --no-install-recommends flatpak bubblewrap || true
  fi
  FLATPAK_BUILD_VERSION=$(flatpak --version 2>/dev/null | awk '{print $2}' || true)
  BWRAP_BUILD_VERSION=$(bwrap --version 2>/dev/null | awk '{print $2}' || true)
  log "Flatpak build runtime: ${FLATPAK_BUILD_VERSION:-unknown}; bubblewrap: ${BWRAP_BUILD_VERSION:-unknown}"
  if [[ -n "$FLATPAK_BUILD_VERSION" ]] && command -v dpkg >/dev/null 2>&1 && dpkg --compare-versions "$FLATPAK_BUILD_VERSION" eq 1.16.5; then
    log "warning: Flatpak 1.16.5 has a known upstream /proc/self/fd sandbox regression fixed in 1.16.6"
    log "warning: vendor-native APT resolvers are used for captured APT Code/Signal; true Flatpak captures still remain Flatpak"
  fi

  # Flatpak extra-data apps (for example proprietary vendor wrappers) execute
  # /app/bin/apply_extra inside a bubblewrap sandbox. Pardus can restrict
  # unprivileged user namespaces even while this image build itself runs as
  # root. Use bubblewrap's documented setuid fallback only for this transient
  # chroot installation window, then restore its package mode immediately.
  BWRAP_BUILD_PATH=$(command -v bwrap)
  BWRAP_BUILD_MODE=$(stat -Lc '%a' "$BWRAP_BUILD_PATH")
  export FLATPAK_BWRAP="$BWRAP_BUILD_PATH"
  chmod u+s "$BWRAP_BUILD_PATH"
  if [[ ! -u "$BWRAP_BUILD_PATH" ]]; then
    log "ERROR: temporary bubblewrap fallback could not be enabled (build filesystem may be nosuid)"
    exit 35
  fi

  # Never let the build host's NVIDIA/kernel state choose target runtime
  # extensions. `default` is Flatpak's stable generic GL fallback. Keep output
  # non-interactive so logs remain deterministic and parseable.
  export FLATPAK_GL_DRIVERS=default
  export FLATPAK_TTY_PROGRESS=0
  export FLATPAK_FANCY_OUTPUT=0

  log "Installing captured Flatpak applications with build-only bubblewrap fallback"
  log "Forcing generic Flatpak GL driver selection; host GPU extensions are excluded"
  flatpak remote-add --system --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo || true
  for app in "${flatpaks[@]}"; do
    if ! flatpak install --system -y flathub "$app"; then
      log "ERROR: required captured application could not be installed: $app"
      exit 31
    fi
    if ! flatpak info --system "$app" >/dev/null 2>&1; then
      log "ERROR: Flatpak reported success but the required app is not deployed: $app"
      exit 36
    fi
  done

  # Shared runtimes are retained, but a versioned NVIDIA extension would bind
  # the ISO to the build machine's driver. With FLATPAK_GL_DRIVERS=default none
  # should be installed; fail rather than silently shipping host-specific state.
  if flatpak list --system --runtime --columns=application 2>/dev/null | grep -Eq '^org\.freedesktop\.Platform\.((GL|GL32)\.nvidia-|VAAPI\.nvidia$|amd\.amf$)'; then
    log "ERROR: host-specific GPU Flatpak runtime leaked into the target image"
    exit 37
  fi

  restore_build_bwrap
  if [[ -u "$BWRAP_BUILD_PATH" ]]; then
    log "ERROR: temporary setuid bubblewrap mode was not removed"
    exit 38
  fi
  BWRAP_BUILD_PATH=""
  BWRAP_BUILD_MODE=""
fi

# Keep the native distro identity and installer packages intact.
exit 0
'''

NATIVE_QEMU_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
DEFAULT_RESULT=__RESULT_Q__
RESULT=${1:-"$DEFAULT_RESULT"}
ISO="$RESULT/__OUTPUT_NAME__"
[[ -f "$ISO" ]] || { echo "Expected native ISO not found: $ISO" >&2; exit 2; }
if [[ -f "$ISO.sha256" ]]; then
  (cd "$RESULT" && sha256sum -c "$(basename "$ISO.sha256")") || { echo "Native ISO checksum verification failed" >&2; exit 2; }
fi
QEMU=$(command -v qemu-system-x86_64 || command -v qemu-kvm || true)
[[ -n "$QEMU" ]] || { echo "qemu-system-x86_64 not found" >&2; exit 2; }
DISK="$RESULT/linux-iso-native-test.qcow2"
command -v qemu-img >/dev/null 2>&1 || { echo "qemu-img not found" >&2; exit 2; }
rm -f "$DISK"
qemu-img create -f qcow2 "$DISK" 40G
ACCEL=(-accel tcg,thread=multi -cpu max,la57=off)
if [[ -r /dev/kvm && -w /dev/kvm ]]; then ACCEL=(-enable-kvm -cpu host); fi
CODE=""; VARS=""
for pair in \
  "/usr/share/OVMF/OVMF_CODE_4M.fd|/usr/share/OVMF/OVMF_VARS_4M.fd" \
  "/usr/share/OVMF/OVMF_CODE.fd|/usr/share/OVMF/OVMF_VARS.fd" \
  "/usr/share/ovmf/OVMF.fd|/usr/share/ovmf/OVMF_VARS.fd"
do
  code=${pair%%|*}; vars=${pair#*|}
  if [[ -f "$code" && -f "$vars" ]]; then CODE="$code"; VARS="$vars"; break; fi
done
args=(-machine q35 "${ACCEL[@]}" -m 4096 -smp 2 -boot once=d,menu=on -drive "file=$DISK,format=qcow2,if=virtio" -cdrom "$ISO" -netdev user,id=net0 -device virtio-net-pci,netdev=net0 -display gtk,gl=off -name "Suret - NATIVE INSTALL / then INSTALLED SYSTEM")
if [[ -n "$CODE" && -n "$VARS" ]]; then
  VARS_COPY="$RESULT/linux-iso-native-OVMF_VARS.fd"; cp "$VARS" "$VARS_COPY"
  args+=( -drive "if=pflash,format=raw,readonly=on,file=$CODE" -drive "if=pflash,format=raw,file=$VARS_COPY" )
else
  echo "warning: no compatible OVMF CODE/VARS pair found; QEMU will use legacy firmware" >&2
fi
exec "$QEMU" "${args[@]}"
'''


def _shell_array(items: list[str]) -> str:
    import shlex
    return " ".join(shlex.quote(x) for x in items)


def _assert_template_rendered(label: str, text: str) -> None:
    tokens = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", text)))
    if tokens:
        raise NativeIsoError(f"Unresolved Native template token(s) in {label}: {', '.join(tokens)}")


def stage_native_project(
    profile: Path,
    base_iso: Path,
    output: Path,
    *,
    result: Path | None = None,
    replace_desktop: bool = False,
) -> Path:
    profile = profile.expanduser().resolve()
    base_iso = base_iso.expanduser().resolve()
    output = output.expanduser().resolve()
    result = (result or (output.parent / "linux-iso-native-result")).expanduser().resolve()

    verification = verify_profile(profile)
    if not verification.ok:
        raise NativeIsoError("Profile verification failed; run `linux-iso verify` first.")

    probe = probe_native_iso(base_iso)
    if not probe.supports_native_build:
        raise NativeIsoError(
            f"Native build adapter is not ready for {probe.distro_id}/{probe.live_rootfs}. "
            "The current build-capable adapter is Pardus 25 x86_64 using /live/filesystem.squashfs."
        )

    manifest = _load_manifest(profile)
    restore_meta = manifest.get("restore") or {}
    profile_version = str(restore_meta.get("profile_version") or "").strip()
    try:
        fidelity_schema = int(restore_meta.get("fidelity_schema") or 0)
    except (TypeError, ValueError):
        fidelity_schema = 0
    if profile_version and fidelity_schema < 11:
        raise NativeIsoError(
            "This profile predates Suret's SDDM/slideshow fidelity schema. "
            "Run scripts/native-acceptance.sh once to recapture the source profile; "
            "retry mode intentionally refuses to guess whether a legacy static wallpaper was originally a slideshow."
        )
    profile_fingerprint = sha256_file(profile / "manifest.yaml")
    source = manifest.get("source", {})
    source_id = str(source.get("distro_id") or "").lower()
    if source_id and source_id != probe.distro_id:
        raise NativeIsoError(
            f"Source profile distro is {source_id!r}, but base ISO is {probe.distro_id!r}. "
            "Native mode intentionally refuses silent cross-distro grafting."
        )
    source_arch = _normalize_architecture(source.get("architecture"))
    base_arch = _normalize_architecture(probe.architecture)
    if source_arch and base_arch and source_arch != "unknown" and base_arch != "unknown" and source_arch != base_arch:
        raise NativeIsoError(
            f"Source profile architecture is {source_arch!r}, but base ISO is {base_arch!r}. "
            "Native mode requires matching architectures."
        )
    if probe.distro_id == "pardus":
        source_major = _version_major(source.get("distro_version"))
        base_major = _version_major(probe.distro_version)
        if source_major and base_major and source_major != base_major:
            raise NativeIsoError(
                f"Source profile is Pardus {source.get('distro_version')!s}, but base ISO is Pardus {probe.distro_version!s}. "
                "Native Pardus mode requires the same major release family."
            )
    desktop = str((manifest.get("desktop") or {}).get("desktop") or "unknown")
    if desktop != "kde-plasma":
        raise NativeIsoError(
            f"The first native adapter currently targets KDE Plasma profiles; got {desktop!r}."
        )

    appearance_packages = _profile_appearance_plan(manifest, probe.package_family)
    native_apps, vendor_apt_apps, flatpaks = _profile_app_plan(manifest, probe.package_family)
    vendor_archive_apps, flatpaks = _split_vendor_archive_flatpaks(flatpaks)
    output_name = f"suret-{probe.distro_id}-{probe.distro_version or 'native'}-kde-amd64.iso"
    output.mkdir(parents=True, exist_ok=True)
    # Marker used by acceptance cleanup to distinguish an intentionally staged
    # Suret Native project from an arbitrary custom directory before any
    # privileged recursive removal is permitted. Keep it user-owned.
    (output / ".suret-native-project").write_text(
        "linux-iso-suret-native-project-v1\n", encoding="utf-8"
    )
    staged_profile = output / "profile"
    # Never merge a fresh profile on top of an older staged payload: stale
    # launchers/assets could otherwise survive into the next ISO, including
    # data that the new profile intentionally stopped carrying.
    if staged_profile.exists() or staged_profile.is_symlink():
        if staged_profile.is_symlink() or staged_profile.is_file():
            staged_profile.unlink()
        else:
            shutil.rmtree(staged_profile)
    shutil.copytree(profile, staged_profile, symlinks=True)

    # Recover browser affinity for web apps that older profiles normalized to
    # xdg-open. This happens before generic launcher restoration so the original
    # Brave app-id/profile command can be consumed without copying browser state.
    webapp_bindings = _rewrite_native_webapp_launchers(staged_profile)
    for resolver_id in webapp_bindings.get("vendor_apt_apps", []):
        if resolver_id not in vendor_apt_apps:
            vendor_apt_apps.append(str(resolver_id))
    for app_id in webapp_bindings.get("flatpaks", []):
        if app_id not in flatpaks:
            flatpaks.append(str(app_id))

    vendor_restore_execs = {
        spec["portable_exec"]
        for spec in VENDOR_APT_RESOLVERS.values()
        if spec["id"] in vendor_apt_apps and spec.get("portable_exec")
    }
    restored_native_launchers = _restore_native_launcher_execs(
        staged_profile, restore_portable_execs=vendor_restore_execs
    )
    rewritten_vendor_archive_launchers = _rewrite_vendor_archive_launcher_execs(
        staged_profile, resolver_ids=set(vendor_archive_apps)
    )

    state = {
        "mode": "native-iso",
        "suret_version": __version__,
        "probe": probe.to_dict(),
        "profile": str(profile),
        "base_iso": str(base_iso),
        "result": str(result),
        "output_name": output_name,
        "target_desktop": desktop,
        "profile_fingerprint": profile_fingerprint,
        "replace_base_desktop": bool(replace_desktop),
        "appearance_packages": appearance_packages,
        "native_apps": native_apps,
        "vendor_apt_apps": vendor_apt_apps,
        "vendor_archive_apps": vendor_archive_apps,
        "flatpaks": flatpaks,
        "webapp_bindings": webapp_bindings,
        "restored_native_launchers": restored_native_launchers,
        "rewritten_vendor_archive_launchers": rewritten_vendor_archive_launchers,
        "visual_fidelity": {
            "slideshow": restore_meta.get("slideshow") or {},
            "sddm": ((restore_meta.get("system_visual") or {}).get("sddm") or {}),
        },
    }
    (output / "native.json").write_text(_safe_json(state), encoding="utf-8")
    (output / "profile/native-restore.json").write_text(
        _safe_json({"schema": 2, "desktop": desktop, "profile_fingerprint": profile_fingerprint}),
        encoding="utf-8",
    )
    (output / "native-first-login.py").write_text(NATIVE_FIRST_LOGIN, encoding="utf-8")
    (output / "native-prelogin.py").write_text(NATIVE_PRELOGIN, encoding="utf-8")
    (output / "native-system-visual.py").write_text(NATIVE_SYSTEM_VISUAL, encoding="utf-8")
    (output / "native-vendor-archive.py").write_text(NATIVE_VENDOR_ARCHIVE_HELPER, encoding="utf-8")
    (output / "linux-iso-native-prelogin.service").write_text(NATIVE_PRELOGIN_SERVICE, encoding="utf-8")
    (output / "linux-iso-native-first-login.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Suret profile convergence\n"
        "Exec=/usr/lib/linux-iso/native-first-login.py\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )

    required_desktop_packages = PARDUS_KDE_REQUIRED_PACKAGES if probe.distro_id == "pardus" else []
    optional_desktop_packages = PARDUS_KDE_OPTIONAL_PACKAGES if probe.distro_id == "pardus" else []
    install_script = NATIVE_INSTALL_SCRIPT
    install_script = install_script.replace("__DISTRO_ID__", probe.distro_id)
    install_script = install_script.replace("__REQUIRED_DESKTOP_PACKAGES__", _shell_array(required_desktop_packages))
    install_script = install_script.replace("__OPTIONAL_DESKTOP_PACKAGES__", _shell_array(optional_desktop_packages))
    install_script = install_script.replace("__REMOVE_PACKAGES__", _shell_array(PARDUS_XFCE_REMOVE_PACKAGES))
    install_script = install_script.replace("__APPEARANCE_PACKAGES__", _shell_array(appearance_packages))
    install_script = install_script.replace("__NATIVE_APPS__", _shell_array(native_apps))
    install_script = install_script.replace("__VENDOR_APT_APPS__", _shell_array(vendor_apt_apps))
    install_script = install_script.replace("__VENDOR_ARCHIVE_APPS__", _shell_array(vendor_archive_apps))
    install_script = install_script.replace("__FLATPAKS__", _shell_array(flatpaks))
    _assert_template_rendered("native-install.sh", install_script)
    (output / "native-install.sh").write_text(install_script, encoding="utf-8")

    build_script = NATIVE_BUILD_SCRIPT
    build_script = build_script.replace("__BASE_ISO_Q__", _shell_array([str(base_iso)]))
    build_script = build_script.replace("__RESULT_Q__", _shell_array([str(result)]))
    build_script = build_script.replace("__ROOTFS_REL__", probe.live_rootfs.lstrip("/"))
    build_script = build_script.replace("__OUTPUT_NAME__", output_name)
    build_script = build_script.replace("__REPLACE_DESKTOP__", "1" if replace_desktop else "0")
    _assert_template_rendered("build-native.sh", build_script)
    (output / "build-native.sh").write_text(build_script, encoding="utf-8")

    qemu = NATIVE_QEMU_SCRIPT.replace("__RESULT_Q__", _shell_array([str(result)]))
    qemu = qemu.replace("__OUTPUT_NAME__", output_name)
    _assert_template_rendered("test-native-qemu.sh", qemu)
    (output / "test-native-qemu.sh").write_text(qemu, encoding="utf-8")
    for path in (output / "build-native.sh", output / "native-install.sh", output / "native-first-login.py", output / "native-prelogin.py", output / "native-system-visual.py", output / "native-vendor-archive.py", output / "test-native-qemu.sh"):
        path.chmod(0o755)
    return output


def run_native_build(project: Path) -> int:
    project = project.expanduser().resolve()
    script = project / "build-native.sh"
    if not script.is_file():
        raise NativeIsoError(f"Native build script not found: {script}")
    proc = subprocess.run([str(script)], cwd=project, check=False)
    return int(proc.returncode)
