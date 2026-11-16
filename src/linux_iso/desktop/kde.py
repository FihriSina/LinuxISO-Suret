from __future__ import annotations

import configparser
import json
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
    ".config/Kvantum/kvantum.kvconfig",
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
    ".local/share/konsole",
]

PLUGIN_RE = re.compile(r"^plugin\s*=\s*(.+?)\s*$", re.MULTILINE)


QML_IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE)


def plasmoid_runtime_details(path: Path) -> dict[str, object]:
    """Collect lightweight runtime metadata for a bundled Plasma widget.

    Plasma 6 widgets are self-contained KPackage directories, but their QML may
    import additional modules. We preserve the full widget bundle and record
    import hints so portability checks can flag unusual external runtimes without
    pretending to map every QML module to a distro package.
    """
    metadata_path = path / "metadata.json"
    metadata: dict[str, object] = {}
    if metadata_path.is_file():
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            metadata = raw

    imports: set[str] = set()
    if path.is_dir():
        try:
            qml_files = list(path.rglob("*.qml"))
        except OSError:
            qml_files = []
        for qml in qml_files:
            try:
                text = qml.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            imports.update(QML_IMPORT_RE.findall(text))

    # Qt and KDE namespaces are expected to be supplied by the Plasma runtime.
    # Anything else is not necessarily broken, but deserves a portability hint.
    external = sorted(
        module for module in imports
        if not (module.startswith("Qt") or module.startswith("org.kde."))
    )
    plugin = metadata.get("KPlugin") if isinstance(metadata, dict) else None
    plugin = plugin if isinstance(plugin, dict) else {}
    return {
        "qml_imports": sorted(imports),
        "external_qml_imports": external,
        "plasma_api_minimum_version": metadata.get("X-Plasma-API-Minimum-Version") if isinstance(metadata, dict) else None,
        "kpackage_structure": metadata.get("KPackageStructure") if isinstance(metadata, dict) else None,
        "widget_version": plugin.get("Version") if isinstance(plugin, dict) else None,
    }


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
        ("gtk-theme", home / ".config/gtk-3.0/settings.ini", "Settings", "gtk-theme-name"),
        ("gtk-theme", home / ".config/gtk-4.0/settings.ini", "Settings", "gtk-theme-name"),
        ("kvantum-theme", home / ".config/Kvantum/kvantum.kvconfig", "General", "theme"),
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

    # Aurorae stores the selected decoration in kwinrc with a synthetic prefix.
    # Preserve the actual package/theme name so it can be resolved and bundled.
    decoration = _read_ini_value(
        home / ".config/kwinrc", "org.kde.kdecoration2", "theme"
    )
    if decoration:
        prefix = "__aurorae__svg__"
        name = decoration[len(prefix):] if decoration.startswith(prefix) else decoration
        token = ("window-decoration", name)
        if token not in seen:
            seen.add(token)
            result.append({"kind": "window-decoration", "name": name})
    return result


def _component_aliases(path: Path) -> set[str]:
    """Return identifiers/names advertised by a KDE package directory or file."""
    aliases = {path.name, path.stem}

    metadata_json = path / "metadata.json" if path.is_dir() else None
    if metadata_json and metadata_json.is_file():
        try:
            data = json.loads(metadata_json.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            data = {}
        plugin = data.get("KPlugin") if isinstance(data, dict) else None
        if isinstance(plugin, dict):
            for key in ("Id", "Name"):
                value = plugin.get(key)
                if isinstance(value, str) and value.strip():
                    aliases.add(value.strip())

    metadata_desktop = path / "metadata.desktop" if path.is_dir() else None
    if metadata_desktop and metadata_desktop.is_file():
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        try:
            parser.read(metadata_desktop, encoding="utf-8")
        except (OSError, configparser.Error):
            pass
        else:
            if parser.has_section("Desktop Entry"):
                for key in ("X-KDE-PluginInfo-Name", "Name"):
                    value = parser.get("Desktop Entry", key, fallback="").strip()
                    if value:
                        aliases.add(value)

    index_theme = path / "index.theme" if path.is_dir() else None
    if index_theme and index_theme.is_file():
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        try:
            parser.read(index_theme, encoding="utf-8")
        except (OSError, configparser.Error):
            pass
        else:
            for section in ("Icon Theme", "Desktop Entry"):
                if parser.has_section(section):
                    value = parser.get(section, "Name", fallback="").strip()
                    if value:
                        aliases.add(value)

    return aliases


def _normalized_component_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _resolve_named_entry(root: Path, name: str, *, file_suffix: str | None = None) -> list[Path]:
    """Resolve a KDE component by directory/file name and then by metadata alias.

    KDE configs often store the package Id while third-party themes can live in a
    directory with a different name (for example a reverse-domain folder whose
    metadata advertises Id=Nordic). Exact path matching alone therefore misses
    otherwise valid user-local packages.
    """
    if not root.is_dir():
        return []

    target = _normalized_component_name(name)
    matches: list[Path] = []

    exact_name = name if file_suffix is None or name.endswith(file_suffix) else f"{name}{file_suffix}"
    exact = root / exact_name
    if exact.exists():
        matches.append(exact)

    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        return matches

    for entry in entries:
        if entry in matches:
            continue
        if file_suffix is None and not entry.is_dir():
            continue
        if file_suffix is not None and (not entry.is_file() or entry.suffix != file_suffix):
            continue
        if any(_normalized_component_name(alias) == target for alias in _component_aliases(entry)):
            matches.append(entry)
    return matches




def active_kwin_user_components(home: Path) -> list[dict[str, str]]:
    """Return enabled user-installed KWin scripts/effects.

    KWin records enabled plugins in the [Plugins] group of kwinrc as
    <pluginId>Enabled=true. We intentionally return only user-local packages
    here; built-in/system effects are part of the base desktop and should not
    inflate the portable profile.
    """
    path = home / ".config/kwinrc"
    if not path.is_file():
        return []
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return []
    if not parser.has_section("Plugins"):
        return []

    enabled: list[str] = []
    for key, value in parser.items("Plugins"):
        if not key.endswith("Enabled"):
            continue
        if value.strip().casefold() not in {"1", "true", "yes", "on"}:
            continue
        plugin_id = key[:-7].strip()
        if plugin_id:
            enabled.append(plugin_id)

    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    specs = [
        ("kwin-script", home / ".local/share/kwin/scripts"),
        ("kwin-effect", home / ".local/share/kwin/effects"),
    ]
    for plugin_id in sorted(set(enabled), key=str.casefold):
        for kind, root in specs:
            for match in _resolve_named_entry(root, plugin_id):
                token = (kind, match.name)
                if token in seen:
                    continue
                seen.add(token)
                result.append({"kind": kind, "name": match.name, "config_id": plugin_id})
    return result


def component_locations(home: Path, kind: str, name: str) -> tuple[list[Path], list[tuple[Path, Path]]]:
    """Return (user-local paths, system path -> target-relative-path mappings).

    v0.2.2 resolves third-party KDE packages by metadata Id/Name as well as by
    their on-disk directory name, avoiding false `not-found` results for global
    themes such as Nordic.
    """
    if kind in {"icon-theme", "cursor-theme"}:
        user_roots = [home / ".local/share/icons", home / ".icons"]
        system_roots = [Path("/usr/local/share/icons"), Path("/usr/share/icons")]
        target_root = Path(".local/share/icons")
        user = [p for root in user_roots for p in _resolve_named_entry(root, name)]
        system = [
            (p, target_root / p.name)
            for root in system_roots
            for p in _resolve_named_entry(root, name)
        ]
    elif kind in {"look-and-feel", "splash-theme"}:
        user_roots = [home / ".local/share/plasma/look-and-feel"]
        system_roots = [
            Path("/usr/local/share/plasma/look-and-feel"),
            Path("/usr/share/plasma/look-and-feel"),
        ]
        target_root = Path(".local/share/plasma/look-and-feel")
        user = [p for root in user_roots for p in _resolve_named_entry(root, name)]
        system = [
            (p, target_root / p.name)
            for root in system_roots
            for p in _resolve_named_entry(root, name)
        ]
    elif kind == "window-decoration":
        user_specs = [
            (home / ".local/share/aurorae/themes", Path(".local/share/aurorae/themes")),
            (home / ".local/share/kwin/decorations", Path(".local/share/kwin/decorations")),
        ]
        system_specs = [
            (Path("/usr/local/share/aurorae/themes"), Path(".local/share/aurorae/themes")),
            (Path("/usr/share/aurorae/themes"), Path(".local/share/aurorae/themes")),
            (Path("/usr/local/share/kwin/decorations"), Path(".local/share/kwin/decorations")),
            (Path("/usr/share/kwin/decorations"), Path(".local/share/kwin/decorations")),
        ]
        user = [
            p
            for root, _target in user_specs
            for p in _resolve_named_entry(root, name)
        ]
        system = [
            (p, target_root / p.name)
            for root, target_root in system_specs
            for p in _resolve_named_entry(root, name)
        ]
    elif kind == "plasma-theme":
        user_roots = [home / ".local/share/plasma/desktoptheme"]
        system_roots = [
            Path("/usr/local/share/plasma/desktoptheme"),
            Path("/usr/share/plasma/desktoptheme"),
        ]
        target_root = Path(".local/share/plasma/desktoptheme")
        user = [p for root in user_roots for p in _resolve_named_entry(root, name)]
        system = [
            (p, target_root / p.name)
            for root in system_roots
            for p in _resolve_named_entry(root, name)
        ]
    elif kind == "gtk-theme":
        user_roots = [home / ".local/share/themes", home / ".themes"]
        system_roots = [Path("/usr/local/share/themes"), Path("/usr/share/themes")]
        target_root = Path(".local/share/themes")
        user = [p for root in user_roots for p in _resolve_named_entry(root, name)]
        system = [
            (p, target_root / p.name)
            for root in system_roots
            for p in _resolve_named_entry(root, name)
        ]
    elif kind == "kvantum-theme":
        user_roots = [home / ".config/Kvantum", home / ".local/share/Kvantum"]
        system_roots = [Path("/usr/local/share/Kvantum"), Path("/usr/share/Kvantum")]
        target_root = Path(".config/Kvantum")
        user = [p for root in user_roots for p in _resolve_named_entry(root, name)]
        system = [
            (p, target_root / p.name)
            for root in system_roots
            for p in _resolve_named_entry(root, name)
        ]
    elif kind in {"kwin-script", "kwin-effect"}:
        leaf = "scripts" if kind == "kwin-script" else "effects"
        user_roots = [home / ".local/share/kwin" / leaf]
        system_roots = [Path("/usr/local/share/kwin") / leaf, Path("/usr/share/kwin") / leaf]
        target_root = Path(".local/share/kwin") / leaf
        user = [p for root in user_roots for p in _resolve_named_entry(root, name)]
        system = [
            (p, target_root / p.name)
            for root in system_roots
            for p in _resolve_named_entry(root, name)
        ]
    elif kind == "color-scheme":
        user_roots = [home / ".local/share/color-schemes"]
        system_roots = [Path("/usr/local/share/color-schemes"), Path("/usr/share/color-schemes")]
        target_root = Path(".local/share/color-schemes")
        user = [p for root in user_roots for p in _resolve_named_entry(root, name, file_suffix=".colors")]
        system = [
            (p, target_root / p.name)
            for root in system_roots
            for p in _resolve_named_entry(root, name, file_suffix=".colors")
        ]
    else:
        return [], []

    # Keep deterministic ordering and remove duplicates while preserving the first
    # (usually exact-name) match.
    user = list(dict.fromkeys(user))
    system = list(dict.fromkeys(system))
    return user, system


def _icon_theme_inherits(path: Path) -> list[str]:
    index = path / "index.theme"
    if not index.is_file():
        return []
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(index, encoding="utf-8")
    except (OSError, configparser.Error):
        return []
    if not parser.has_section("Icon Theme"):
        return []
    raw = parser.get("Icon Theme", "Inherits", fallback="")
    return [item.strip() for item in raw.split(",") if item.strip()]


def icon_theme_inheritance_chain(home: Path, name: str, max_depth: int = 12) -> list[str]:
    """Return transitive inherited icon themes in deterministic order.

    KDE/FreeDesktop icon themes commonly inherit a base theme. Active-only capture
    must retain that chain or icons can silently disappear on the restored desktop.
    """
    result: list[str] = []
    queued: list[tuple[str, int]] = [(name, 0)]
    seen = {_normalized_component_name(name)}
    while queued:
        current, depth = queued.pop(0)
        if depth >= max_depth:
            continue
        user, system = component_locations(home, "icon-theme", current)
        candidates = list(user) + [path for path, _target in system]
        if not candidates:
            continue
        for inherited in _icon_theme_inherits(candidates[0]):
            normalized = _normalized_component_name(inherited)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(inherited)
            queued.append((inherited, depth + 1))
    return result


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
