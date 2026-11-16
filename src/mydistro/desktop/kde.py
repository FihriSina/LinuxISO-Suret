from __future__ import annotations

import configparser
import re
from pathlib import Path


KDE_CONFIG_FILES = [
    ".config/kdeglobals",
    ".config/kwinrc",
    ".config/plasmashellrc",
    ".config/plasma-org.kde.plasma.desktop-appletsrc",
    ".config/kglobalshortcutsrc",
    ".config/kcminputrc",
    ".config/kscreenlockerrc",
    ".config/ksplashrc",
    ".config/breezerc",
    ".config/dolphinrc",
    ".config/konsolerc",
    ".config/mimeapps.list",
    ".config/Kvantum",
]

KDE_DATA_PATHS = [
    ".local/share/plasma/plasmoids",
    ".local/share/plasma/desktoptheme",
    ".local/share/plasma/look-and-feel",
    ".local/share/plasma/layout-templates",
    ".local/share/aurorae",
    ".local/share/color-schemes",
    ".local/share/konsole",
    ".local/share/wallpapers",
    ".local/share/icons",
    ".icons",
    ".local/share/themes",
    ".themes",
    ".local/share/fonts",
    ".fonts",
    ".local/share/applications",
]

TERMINAL_FILES = [
    ".zshrc",
    ".bashrc",
    ".config/starship.toml",
    ".config/fish/config.fish",
]

PLUGIN_RE = re.compile(r"^plugin\s*=\s*(.+?)\s*$", re.MULTILINE)


def existing_kde_paths(home: Path) -> tuple[list[Path], list[Path], list[Path]]:
    configs = [home / p for p in KDE_CONFIG_FILES if (home / p).exists()]
    data = [home / p for p in KDE_DATA_PATHS if (home / p).exists()]
    terminal = [home / p for p in TERMINAL_FILES if (home / p).exists()]
    return configs, data, terminal


def referenced_widgets(home: Path) -> list[str]:
    path = home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return sorted(set(m.group(1).strip() for m in PLUGIN_RE.finditer(text)))


def user_plasmoids(home: Path) -> list[str]:
    root = home / ".local/share/plasma/plasmoids"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
