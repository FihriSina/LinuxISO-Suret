from __future__ import annotations

import re
import shutil
import subprocess

from mydistro.models import Package


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
    r"plasma|kwin|kvantum|latte|konsole|starship|zsh|fish|nerd[-_ ]?font|papirus|breeze|cursor|theme|qt6ct|qt5ct",
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


def _make(name: str, provider: str) -> Package:
    required = bool(APPEARANCE_RULE.search(name))
    return Package(
        name=name,
        provider=provider,
        category=_categorize(name),
        required_for_appearance=required,
        reason="Package name suggests it participates in desktop appearance." if required else None,
    )


def detect_native_packages() -> list[Package]:
    packages: list[Package] = []

    if shutil.which("apt-mark"):
        for name in _run(["apt-mark", "showmanual"]):
            packages.append(_make(name, "apt"))
    elif shutil.which("pacman"):
        for name in _run(["pacman", "-Qqe"]):
            packages.append(_make(name, "pacman"))
    elif shutil.which("dnf"):
        for line in _run(["dnf", "repoquery", "--userinstalled", "--qf", "%{name}"]):
            packages.append(_make(line, "dnf"))
    elif shutil.which("zypper"):
        # zypper has no cross-version equivalent of apt-mark showmanual.
        # Keep the MVP conservative rather than pretending every installed RPM was user-selected.
        pass

    return packages


def detect_flatpaks() -> list[Package]:
    return [_make(app_id, "flatpak") for app_id in _run(["flatpak", "list", "--app", "--columns=application"])]


def detect_snaps() -> list[Package]:
    lines = _run(["snap", "list"])
    if not lines:
        return []
    result: list[Package] = []
    for line in lines[1:]:
        name = line.split()[0] if line.split() else ""
        if name:
            result.append(_make(name, "snap"))
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
