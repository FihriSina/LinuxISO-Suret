from __future__ import annotations

import configparser
import re
from pathlib import Path


KDE_CONFIG_FILES = [
    ".config/kdeglobals",
    ".config/kwinrc",
    ".config/plasmashellrc",
    ".config/plasmarc",
    ".config/plasma-org.kde.plasma.desktop-appletsrc",
    ".config/kglobalshortcutsrc",
    ".config/kcminputrc",
    ".config/kscreenlockerrc",
    ".config/ksplashrc",
    ".config/breezerc",
    ".config/dolphinrc",
    ".config/konsolerc",
    ".config/mimeapps.list",
    ".config/gtk-3.0/settings.ini",
    ".config/gtk-4.0/settings.ini",
    ".config/qt5ct/qt5ct.conf",
    ".config/qt6ct/qt6ct.conf",
    ".config/Kvantum",
]

KDE_DATA_PATHS = [
    ".local/share/plasma/plasmoids",
    ".local/share/plasma/desktoptheme",
    ".local/share/plasma/look-and-feel",
    ".local/share/plasma/layout-templates",
    ".local/share/aurorae",
    ".local/share/kwin/scripts",
    ".local/share/kwin/effects",
    ".local/share/kwin/tabbox",
    ".local/share/kwin/decorations",
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
    ".config/zsh",
    ".oh-my-zsh",
    ".config/kitty",
    ".config/alacritty",
    ".config/wezterm",
    ".config/ghostty",
    ".config/foot",
    ".config/terminator",
    ".config/yakuakerc",
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


def system_plasmoid(plugin_id: str) -> Path | None:
    path = Path("/usr/share/plasma/plasmoids") / plugin_id
    return path if path.is_dir() else None


def package_owner(path: Path) -> tuple[str, str] | None:
    import shutil
    import subprocess

    if shutil.which("dpkg-query"):
        try:
            proc = subprocess.run(
                ["dpkg-query", "-S", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0 and ":" in proc.stdout:
                name = proc.stdout.split(":", 1)[0].strip()
                if name:
                    return "apt", name
        except (OSError, subprocess.TimeoutExpired):
            pass

    if shutil.which("pacman"):
        try:
            proc = subprocess.run(
                ["pacman", "-Qo", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                marker = " is owned by "
                if marker in proc.stdout:
                    tail = proc.stdout.split(marker, 1)[1].strip()
                    name = tail.split()[0] if tail else ""
                    if name:
                        return "pacman", name
        except (OSError, subprocess.TimeoutExpired):
            pass

    if shutil.which("rpm"):
        try:
            proc = subprocess.run(
                ["rpm", "-qf", "--qf", "%{NAME}\\n", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                provider = "dnf" if shutil.which("dnf") else "zypper"
                return provider, proc.stdout.strip().splitlines()[0]
        except (OSError, subprocess.TimeoutExpired):
            pass

    return None



def _read_ini_value(path: Path, section: str, key: str) -> str | None:
    if not path.is_file():
        return None
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return None
    if not parser.has_section(section):
        return None
    value = parser.get(section, key, fallback=None)
    return value.strip() if value and value.strip() else None


def active_kde_components(home: Path) -> list[dict[str, str]]:
    """Return active appearance components that can resolve to portable/system assets."""
    checks = [
        ("icon-theme", home / ".config/kdeglobals", "Icons", "Theme"),
        ("look-and-feel", home / ".config/kdeglobals", "KDE", "LookAndFeelPackage"),
        ("color-scheme", home / ".config/kdeglobals", "General", "ColorScheme"),
        ("plasma-theme", home / ".config/plasmarc", "Theme", "name"),
        ("cursor-theme", home / ".config/kcminputrc", "Mouse", "cursorTheme"),
        ("splash-theme", home / ".config/ksplashrc", "KSplash", "Theme"),
    ]
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, path, section, key in checks:
        value = _read_ini_value(path, section, key)
        if not value:
            continue
        token = (kind, value)
        if token in seen:
            continue
        seen.add(token)
        result.append({"kind": kind, "name": value})
    return result


def component_locations(home: Path, kind: str, name: str) -> tuple[list[Path], list[tuple[Path, Path]]]:
    """Return (user-local paths, system path -> target-relative-path mappings)."""
    if kind in {"icon-theme", "cursor-theme"}:
        user = [home / ".local/share/icons" / name, home / ".icons" / name]
        system = [
            (Path("/usr/local/share/icons") / name, Path(".local/share/icons") / name),
            (Path("/usr/share/icons") / name, Path(".local/share/icons") / name),
        ]
    elif kind == "look-and-feel" or kind == "splash-theme":
        user = [home / ".local/share/plasma/look-and-feel" / name]
        system = [
            (Path("/usr/local/share/plasma/look-and-feel") / name, Path(".local/share/plasma/look-and-feel") / name),
            (Path("/usr/share/plasma/look-and-feel") / name, Path(".local/share/plasma/look-and-feel") / name),
        ]
    elif kind == "plasma-theme":
        user = [home / ".local/share/plasma/desktoptheme" / name]
        system = [
            (Path("/usr/local/share/plasma/desktoptheme") / name, Path(".local/share/plasma/desktoptheme") / name),
            (Path("/usr/share/plasma/desktoptheme") / name, Path(".local/share/plasma/desktoptheme") / name),
        ]
    elif kind == "color-scheme":
        filename = name if name.endswith(".colors") else f"{name}.colors"
        user = [home / ".local/share/color-schemes" / filename]
        system = [
            (Path("/usr/local/share/color-schemes") / filename, Path(".local/share/color-schemes") / filename),
            (Path("/usr/share/color-schemes") / filename, Path(".local/share/color-schemes") / filename),
        ]
    else:
        return [], []
    return user, system


def ownership_probe(path: Path) -> Path:
    if path.is_file():
        return path
    for preferred in ("metadata.json", "metadata.desktop", "index.theme"):
        candidate = path / preferred
        if candidate.is_file():
            return candidate
    if path.is_dir():
        try:
            return next(p for p in path.rglob("*") if p.is_file())
        except (StopIteration, OSError):
            pass
    return path
