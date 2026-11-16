from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from linux_iso.models import Package


CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("internet", re.compile(r"firefox|chromium|chrome|vivaldi|brave|thunderbird", re.I)),
    ("development", re.compile(r"code|vscode|git|docker|podman|python|nodejs|rust|gcc|clang|cmake|jetbrains", re.I)),
    ("multimedia", re.compile(r"vlc|mpv|obs|gimp|inkscape|krita|kdenlive|ffmpeg|blender|audacity", re.I)),
    ("gaming", re.compile(r"steam|lutris|heroic|wine|proton", re.I)),
    ("communication", re.compile(r"discord|telegram|signal|slack|zoom|teams", re.I)),
    ("office", re.compile(r"libreoffice|onlyoffice|okular|calibre", re.I)),
    ("system", re.compile(r"timeshift|btop|htop|neofetch|fastfetch|partitionmanager", re.I)),
]

APPEARANCE_RULE = re.compile(
    r"plasma|kwin|kvantum|latte|konsole|kitty|alacritty|wezterm|ghostty|yakuake|tilix|terminator|starship|zsh|fish|nerd[-_ ]?font|papirus|breeze|cursor|theme|qt6ct|qt5ct",
    re.I,
)

# Command-line programs that are meaningful end-user choices even without a .desktop file.
CLI_APP_RULE = re.compile(
    r"^(git|docker(?:\.io)?|podman|python3?|nodejs|npm|rustup|cargo|gcc|g\+\+|clang|cmake|"
    r"btop|htop|fastfetch|neofetch|zsh|fish|starship|ffmpeg|yt-dlp|tmux|neovim|vim)$",
    re.I,
)


def _run(command: list[str]) -> list[str]:
    if shutil.which(command[0]) is None:
        return []
    try:
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _categorize(name: str) -> str:
    for category, pattern in CATEGORY_RULES:
        if pattern.search(name):
            return category
    return "other"


def _make(
    name: str,
    provider: str,
    source: str | None = None,
    source_url: str | None = None,
    installer_visible: bool = True,
    visibility_reason: str | None = None,
    install_options: list[str] | None = None,
) -> Package:
    required = bool(APPEARANCE_RULE.search(name))
    return Package(
        name=name,
        provider=provider,
        category=_categorize(name),
        required_for_appearance=required,
        reason="Package name suggests it participates in desktop appearance." if required else None,
        source=source,
        source_url=source_url,
        installer_visible=installer_visible,
        visibility_reason=visibility_reason,
        install_options=list(install_options or []),
    )


def _desktop_entry_paths() -> list[str]:
    roots = [Path("/usr/share/applications"), Path("/usr/local/share/applications")]
    return [str(p) for root in roots if root.is_dir() for p in root.glob("*.desktop") if p.is_file()]


def _apt_desktop_packages(paths: list[str]) -> set[str]:
    if not paths or shutil.which("dpkg-query") is None:
        return set()
    # Keep individual batches below typical ARG_MAX even on large desktops.
    owners: set[str] = set()
    for start in range(0, len(paths), 200):
        for line in _run(["dpkg-query", "-S", *paths[start : start + 200]]):
            if ": " not in line:
                continue
            owner_part = line.rsplit(": ", 1)[0]
            for raw in owner_part.split(","):
                name = raw.strip()
                # Strip Debian multiarch suffix (package:amd64) but not arbitrary colons.
                if name.count(":") == 1 and name.rsplit(":", 1)[1] in {
                    "amd64", "arm64", "armhf", "i386", "ppc64el", "riscv64", "s390x"
                }:
                    name = name.rsplit(":", 1)[0]
                if name:
                    owners.add(name)
    return owners


def _pacman_desktop_packages(paths: list[str]) -> set[str]:
    if not paths or shutil.which("pacman") is None:
        return set()
    owners: set[str] = set()
    for start in range(0, len(paths), 200):
        for line in _run(["pacman", "-Qo", *paths[start : start + 200]]):
            marker = " is owned by "
            if marker in line:
                tail = line.split(marker, 1)[1]
                name = tail.split()[0] if tail else ""
                if name:
                    owners.add(name)
    return owners


def _rpm_desktop_packages(paths: list[str]) -> set[str]:
    if not paths or shutil.which("rpm") is None:
        return set()
    owners: set[str] = set()
    for start in range(0, len(paths), 200):
        owners.update(_run(["rpm", "-qf", "--qf", "%{NAME}\\n", *paths[start : start + 200]]))
    return owners


def _desktop_packages(provider: str) -> set[str]:
    paths = _desktop_entry_paths()
    if provider == "apt":
        return _apt_desktop_packages(paths)
    if provider == "pacman":
        return _pacman_desktop_packages(paths)
    if provider in {"dnf", "zypper"}:
        return _rpm_desktop_packages(paths)
    return set()


def _native_visibility(name: str, provider: str, desktop_owners: set[str]) -> tuple[bool, str]:
    if name in desktop_owners:
        return True, "Package owns a desktop application launcher."
    if CLI_APP_RULE.search(name):
        return True, "Recognized end-user command-line application."
    if _categorize(name) != "other":
        return True, "Recognized application category."
    if APPEARANCE_RULE.search(name):
        return True, "Potential desktop appearance dependency."
    return False, "Manual native package retained in manifest but hidden from the app chooser."


def detect_native_packages() -> list[Package]:
    provider = None
    names: list[str] = []

    if shutil.which("apt-mark"):
        provider = "apt"
        names = _run(["apt-mark", "showmanual"])
    elif shutil.which("pacman"):
        provider = "pacman"
        names = _run(["pacman", "-Qqe"])
    elif shutil.which("dnf"):
        provider = "dnf"
        names = _run(["dnf", "repoquery", "--userinstalled", "--qf", "%{name}"])
    elif shutil.which("zypper"):
        # There is no stable cross-version zypper equivalent of apt-mark showmanual.
        return []

    if not provider:
        return []

    desktop_owners = _desktop_packages(provider)
    result: list[Package] = []
    for name in names:
        visible, reason = _native_visibility(name, provider, desktop_owners)
        result.append(
            _make(
                name,
                provider,
                installer_visible=visible,
                visibility_reason=reason,
            )
        )
    return result


def detect_flatpaks() -> list[Package]:
    remotes: dict[str, str] = {}
    for line in _run(["flatpak", "remotes", "--columns=name,url"]):
        parts = line.split("\t", 1)
        if parts and parts[0].strip():
            remotes[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else ""

    lines = _run(["flatpak", "list", "--app", "--columns=application,origin"])
    result: list[Package] = []
    for line in lines:
        parts = line.split("\t")
        app_id = parts[0].strip() if parts else ""
        origin = parts[1].strip() if len(parts) > 1 else None
        if app_id:
            result.append(
                _make(
                    app_id,
                    "flatpak",
                    source=origin or None,
                    source_url=remotes.get(origin or "") or None,
                    installer_visible=True,
                    visibility_reason="Flatpak application.",
                )
            )
    return result


SNAP_SYSTEM_RULE = re.compile(
    r"^(?:snapd|bare|core(?:18|20|22|24|26)?|gtk-common-themes|gnome-[0-9-]+|kde-frameworks-[0-9-].*)$",
    re.I,
)


def detect_snaps() -> list[Package]:
    lines = _run(["snap", "list"])
    if not lines:
        return []
    result: list[Package] = []
    for line in lines[1:]:
        parts = line.split()
        name = parts[0] if parts else ""
        if not name:
            continue
        channel = parts[3] if len(parts) > 3 else None
        notes = parts[-1].lower() if len(parts) > 5 else ""
        visible = not bool(SNAP_SYSTEM_RULE.search(name))
        result.append(
            _make(
                name,
                "snap",
                source=channel,
                installer_visible=visible,
                visibility_reason=(
                    "Snap application/package."
                    if visible
                    else "Snap base/content package retained but hidden from chooser."
                ),
                install_options=["--classic"] if "classic" in notes else [],
            )
        )
    return result


def collect_packages() -> list[Package]:
    seen: set[tuple[str, str]] = set()
    output: list[Package] = []
    for pkg in detect_native_packages() + detect_flatpaks() + detect_snaps():
        key = (pkg.provider, pkg.name)
        if key not in seen:
            output.append(pkg)
            seen.add(key)
    return sorted(output, key=lambda p: (p.category, p.provider, p.name.lower()))
