from __future__ import annotations

import configparser
import re
import shutil
import subprocess
from pathlib import Path

from linux_iso.models import Package


# These rules intentionally use separators / complete package names instead of broad
# substring matching.  In v0.2, "microcode" was classified as development because
# it contains "code", and "libfishcamp" was treated as an appearance dependency
# because it contains "fish".
CATEGORY_PATTERNS: list[tuple[str, tuple[re.Pattern[str], ...]]] = [
    (
        "internet",
        tuple(
            re.compile(p, re.I)
            for p in (
                r"(?:^|[._-])firefox(?:[._-]|$)",
                r"(?:^|[._-])chromium(?:[._-]|$)",
                r"(?:^|[._-])chrome(?:[._-]|$)",
                r"(?:^|[._-])brave(?:[._-]|$)",
                r"(?:^|[._-])vivaldi(?:[._-]|$)",
                r"(?:^|[._-])opera(?:[._-]|$)",
                r"(?:^|[._-])floorp(?:[._-]|$)",
                r"(?:^|[._-])zen(?:[_-]?browser)?(?:[._-]|$)",
                r"(?:^|[._-])torbrowser(?:[._-]|$)",
                r"(?:^|[._-])thunderbird(?:[._-]|$)",
            )
        ),
    ),
    (
        "development",
        tuple(
            re.compile(p, re.I)
            for p in (
                r"^(?:code|code-insiders|vscodium)$",
                r"^(?:git|cmake|docker(?:\.io)?|podman|rustup|cargo|nodejs|npm|neovim|vim)$",
                r"(?:^|[._-])androidstudio(?:[._-]|$)",
                r"(?:^|[._-])jetbrains(?:[._-]|$)",
            )
        ),
    ),
    (
        "multimedia",
        tuple(
            re.compile(p, re.I)
            for p in (
                r"^(?:vlc|mpv|obs-studio|gimp|inkscape|krita|kdenlive|ffmpeg|blender|audacity)$",
                r"(?:^|[._-])freetube(?:[._-]|$)",
                r"(?:^|[._-])koko(?:[._-]|$)",
            )
        ),
    ),
    (
        "gaming",
        tuple(
            re.compile(p, re.I)
            for p in (
                r"^(?:steam|lutris|heroic|wine|proton)$",
                r"(?:^|[._-])steam(?:[._-]|$)",
                r"(?:^|[._-])heroic(?:[._-]|$)",
            )
        ),
    ),
    (
        "communication",
        tuple(
            re.compile(p, re.I)
            for p in (
                r"^(?:discord|telegram-desktop|signal-desktop|slack|zoom|teams-for-linux)$",
                r"(?:^|[._-])discord(?:[._-]|$)",
                r"(?:^|[._-])telegram(?:[._-]|$)",
                r"(?:^|[._-])signal(?:[._-]|$)",
                r"(?:^|[._-])slack(?:[._-]|$)",
                r"(?:^|[._-])zoom(?:[._-]|$)",
            )
        ),
    ),
    (
        "office",
        tuple(
            re.compile(p, re.I)
            for p in (
                r"^(?:libreoffice|onlyoffice-desktopeditors|okular|calibre)$",
                r"(?:^|[._-])onlyoffice(?:[._-]|$)",
            )
        ),
    ),
    (
        "system",
        tuple(
            re.compile(p, re.I)
            for p in (
                r"^(?:timeshift|btop|htop|neofetch|fastfetch|partitionmanager)$",
                r"(?:^|[._-])flameshot(?:[._-]|$)",
            )
        ),
    ),
]

# Package-name inference is only a fallback. Concrete widget/theme ownership found
# by capture.py always wins and marks the exact package as required.
APPEARANCE_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"^(?:kde-plasma-desktop|plasma-desktop|plasma-workspace|kwin|kwin-x11|kwin-wayland)$",
        r"^(?:kvantum|qt5ct|qt6ct|latte-dock)$",
        r"^(?:konsole|kitty|alacritty|wezterm|ghostty|yakuake|tilix|terminator|starship|zsh|fish)$",
        r"^(?:papirus-icon-theme|breeze-cursor-theme)$",
        r".*(?:icon|cursor)[-_]?theme$",
        r".*nerd[-_]?fonts?.*",
    )
)

# Native packages matching these patterns are retained in the manifest but are not
# shown as optional applications. They are runtimes, libraries, hardware/base
# packages, headers, or implementation dependencies rather than user-facing apps.
SYSTEMISH_NATIVE_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r".*-microcode$",
        r".*-(?:dev|dbg|dbgsym|headers)$",
        r"^lib.+(?:\d|t64)(?:[-+.:a-z0-9]*)$",
        r"^(?:gcc|cpp)-\d+-base$",
        r"^python3(?:\.\d+)?(?:-|$)",
        r"^(?:dmidecode|extra-cmake-modules)$",
        r"^(?:base-files|base-passwd|adduser|apt|apt-utils|bash|bash-completion)$",
    )
)

# Command-line programs that are meaningful end-user choices even without a
# .desktop launcher. Language runtimes and low-level toolchain dependencies are
# deliberately excluded here.
CLI_APP_RULE = re.compile(
    r"^(?:git|docker(?:\.io)?|podman|cmake|rustup|cargo|nodejs|npm|btop|htop|fastfetch|"
    r"neofetch|yt-dlp|tmux|neovim|vim|ffmpeg)$",
    re.I,
)

FREEDESKTOP_CATEGORY_MAP: tuple[tuple[str, set[str]], ...] = (
    ("development", {"Development", "IDE", "TextEditor"}),
    ("internet", {"Network", "WebBrowser", "Email"}),
    ("multimedia", {"AudioVideo", "Audio", "Video", "Graphics", "Photography"}),
    ("gaming", {"Game"}),
    ("office", {"Office"}),
    ("system", {"System", "Settings", "Utility"}),
)


def _run(command: list[str]) -> list[str]:
    if shutil.which(command[0]) is None:
        return []
    try:
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _categorize(name: str, desktop_categories: set[str] | None = None) -> str:
    if desktop_categories:
        # Communication has no single standardized freedesktop top-level category,
        # so package/app-id rules get first chance for those apps.
        explicit = _categorize_by_name(name)
        if explicit in {"communication", "gaming", "internet", "office", "multimedia"}:
            return explicit
        for category, values in FREEDESKTOP_CATEGORY_MAP:
            if desktop_categories & values:
                return category
    return _categorize_by_name(name)


def _categorize_by_name(name: str) -> str:
    for category, patterns in CATEGORY_PATTERNS:
        if any(pattern.search(name) for pattern in patterns):
            return category
    return "other"


def _is_systemish_native(name: str) -> bool:
    return any(pattern.fullmatch(name) or pattern.search(name) for pattern in SYSTEMISH_NATIVE_PATTERNS)


def _appearance_by_name(name: str) -> bool:
    if _is_systemish_native(name):
        return False
    return any(pattern.fullmatch(name) or pattern.search(name) for pattern in APPEARANCE_PATTERNS)


def _make(
    name: str,
    provider: str,
    source: str | None = None,
    source_url: str | None = None,
    installer_visible: bool = True,
    visibility_reason: str | None = None,
    install_options: list[str] | None = None,
    desktop_categories: set[str] | None = None,
) -> Package:
    required = provider != "flatpak" and _appearance_by_name(name)
    return Package(
        name=name,
        provider=provider,
        category=_categorize(name, desktop_categories),
        required_for_appearance=required,
        reason="Package name strongly suggests it participates in desktop appearance." if required else None,
        source=source,
        source_url=source_url,
        installer_visible=installer_visible,
        visibility_reason=visibility_reason,
        install_options=list(install_options or []),
    )


def _desktop_entry_paths() -> list[Path]:
    roots = [Path("/usr/share/applications"), Path("/usr/local/share/applications")]
    return [p for root in roots if root.is_dir() for p in root.glob("*.desktop") if p.is_file()]


def _desktop_categories(path: Path) -> set[str]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return set()
    if not parser.has_section("Desktop Entry"):
        return set()
    raw = parser.get("Desktop Entry", "Categories", fallback="")
    return {item for item in raw.split(";") if item}


def _apt_owner_map(paths: list[Path]) -> dict[Path, str]:
    if not paths or shutil.which("dpkg-query") is None:
        return {}
    owners: dict[Path, str] = {}
    raw_paths = [str(path) for path in paths]
    for start in range(0, len(raw_paths), 200):
        for line in _run(["dpkg-query", "-S", *raw_paths[start : start + 200]]):
            if ": " not in line:
                continue
            owner_part, file_part = line.rsplit(": ", 1)
            # dpkg-query can return several owners; the first concrete package is
            # sufficient for launcher classification.
            raw = owner_part.split(",", 1)[0].strip()
            if raw.count(":") == 1 and raw.rsplit(":", 1)[1] in {
                "amd64", "arm64", "armhf", "i386", "ppc64el", "riscv64", "s390x"
            }:
                raw = raw.rsplit(":", 1)[0]
            if raw:
                owners[Path(file_part)] = raw
    return owners


def _pacman_owner_map(paths: list[Path]) -> dict[Path, str]:
    owners: dict[Path, str] = {}
    if not paths or shutil.which("pacman") is None:
        return owners
    raw_paths = [str(path) for path in paths]
    for start in range(0, len(raw_paths), 200):
        for line in _run(["pacman", "-Qo", *raw_paths[start : start + 200]]):
            marker = " is owned by "
            if marker not in line:
                continue
            path_part, tail = line.split(marker, 1)
            name = tail.split()[0] if tail else ""
            if name:
                owners[Path(path_part)] = name
    return owners


def _rpm_owner_map(paths: list[Path]) -> dict[Path, str]:
    owners: dict[Path, str] = {}
    if not paths or shutil.which("rpm") is None:
        return owners
    # Query one-by-one so we can preserve the file -> owner association.
    for path in paths:
        lines = _run(["rpm", "-qf", "--qf", "%{NAME}\\n", str(path)])
        if lines:
            owners[path] = lines[0]
    return owners


def _native_desktop_info(provider: str) -> dict[str, set[str]]:
    paths = _desktop_entry_paths()
    if provider == "apt":
        owner_map = _apt_owner_map(paths)
    elif provider == "pacman":
        owner_map = _pacman_owner_map(paths)
    elif provider in {"dnf", "zypper"}:
        owner_map = _rpm_owner_map(paths)
    else:
        owner_map = {}

    result: dict[str, set[str]] = {}
    for path, owner in owner_map.items():
        result.setdefault(owner, set()).update(_desktop_categories(path))
    return result


def _native_visibility(
    name: str,
    desktop_info: dict[str, set[str]],
) -> tuple[bool, str, set[str]]:
    categories = desktop_info.get(name, set())
    if name in desktop_info:
        return True, "Package owns a desktop application launcher.", categories
    if _is_systemish_native(name):
        return False, "Runtime/library/hardware/base package retained but hidden from chooser.", categories
    if CLI_APP_RULE.fullmatch(name):
        return True, "Recognized end-user command-line application.", categories
    if _categorize_by_name(name) != "other":
        return True, "Recognized end-user application category.", categories
    if _appearance_by_name(name):
        return True, "Potential desktop appearance dependency.", categories
    return False, "Manual native package retained in manifest but hidden from the app chooser.", categories


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

    desktop_info = _native_desktop_info(provider)
    result: list[Package] = []
    for name in names:
        visible, reason, desktop_categories = _native_visibility(name, desktop_info)
        result.append(
            _make(
                name,
                provider,
                installer_visible=visible,
                visibility_reason=reason,
                desktop_categories=desktop_categories,
            )
        )
    return result


def _flatpak_desktop_categories(app_id: str) -> set[str]:
    candidates = [
        Path.home() / ".local/share/flatpak/exports/share/applications" / f"{app_id}.desktop",
        Path("/var/lib/flatpak/exports/share/applications") / f"{app_id}.desktop",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return _desktop_categories(candidate)
    return set()


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
                    desktop_categories=_flatpak_desktop_categories(app_id),
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
