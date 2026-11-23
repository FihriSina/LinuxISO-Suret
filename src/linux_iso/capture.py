from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import quote, unquote, urlparse

import yaml

from linux_iso import __version__
from linux_iso.assets import find_referenced_assets, sha256_file
from linux_iso.desktop.kde import (
    active_kde_components,
    active_kwin_user_components,
    component_locations,
    existing_kde_paths,
    package_owner,
    plasmoid_runtime_details,
    ownership_probe,
    icon_theme_inheritance_chain,
    referenced_application_desktops,
    referenced_widgets,
    system_plasmoid,
    user_plasmoids,
)
from linux_iso.models import CapturedFile, DesktopProfile, Manifest, Package
from linux_iso.packages.inventory import collect_packages
from linux_iso.security.sanitizer import path_is_sensitive, sanitize_desktop_text, sanitize_shell_text
from linux_iso.system import collect_system_info, detect_desktop


TEXT_EXTENSIONS = {
    "", ".conf", ".ini", ".rc", ".list", ".desktop", ".profile", ".toml", ".fish", ".zsh", ".bash", ".json", ".xml", ".qml",
}

SHELL_FILES = {".zshrc", ".bashrc", "config.fish"}
SHELL_EXTENSIONS = {".zsh", ".bash", ".fish", ".sh"}
KACTIVITY_FAVORITES_AGENT = "org.kde.plasma.favorites.applications"
WALLPAPER_IMAGE_EXTENSIONS = {
    ".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".jxl", ".png", ".svg", ".svgz", ".webp"
}

# Cross-distribution launcher compatibility.  These commands are desktop
# conveniences from Pardus rather than portable application contracts.  Keep
# the user-visible launcher while translating the action to an equivalent KDE
# operation available in the Ubuntu/KDE target.
DESKTOP_EXEC_COMPAT_REPLACEMENTS = {
    # Plasma 6 no longer exposes the historical computer:/ KIO protocol on
    # modern KDE installs. Keep the familiar Bilgisayar launcher but open a
    # portable Dolphin filesystem view instead.
    "pardus-mycomputer": "dolphin /",
    # Pardus-specific control applications have no guaranteed Ubuntu package.
    # Preserve their labels/icons while redirecting to KDE-native equivalents.
    "pardus-about": "kinfocenter",
    "pardus-update": "plasma-discover --mode update",
    "pardus-software": "plasma-discover",
    "pardus-software-center": "plasma-discover",
    "pardus-power-manager": "systemsettings kcm_powerdevilprofilesconfig",
    "pardus-java-installer": "plasma-discover",
    # Portable app fallbacks used by the installer catalog. Rewriting the
    # source launcher at capture time keeps pinned/favorite entries functional.
    "code": "flatpak run com.visualstudio.code",
    "/usr/share/code/code": "flatpak run com.visualstudio.code",
    "signal-desktop": "flatpak run org.signal.Signal",
    "steam": "flatpak run com.valvesoftware.Steam",
}



def _read_grub_defaults() -> dict[str, str]:
    values: dict[str, str] = {}
    files = [Path("/etc/default/grub")]
    confd = Path("/etc/default/grub.d")
    if confd.is_dir():
        files.extend(sorted(confd.glob("*.cfg")))
    wanted = {
        "GRUB_THEME", "GRUB_BACKGROUND", "GRUB_GFXMODE", "GRUB_GFXPAYLOAD_LINUX",
        "GRUB_TIMEOUT_STYLE", "GRUB_TIMEOUT", "GRUB_DISTRIBUTOR",
    }
    for path in files:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in wanted:
                continue
            value = value.strip().strip('"').strip("'")
            if value:
                values[key] = value
    return values


def _read_sddm_theme(
    *,
    vendor_confd: Path = Path("/usr/lib/sddm/sddm.conf.d"),
    etc_confd: Path = Path("/etc/sddm.conf.d"),
    main_config: Path = Path("/etc/sddm.conf"),
) -> dict[str, str]:
    values: dict[str, str] = {}
    # SDDM precedence is vendor drop-ins -> /etc drop-ins -> /etc/sddm.conf.
    # Reading these in the opposite order can capture a distro default instead
    # of the login theme the user actually selected in System Settings.
    files: list[Path] = []
    for confd in (vendor_confd, etc_confd):
        if confd.is_dir():
            files.extend(sorted(path for path in confd.iterdir() if path.is_file()))
    files.append(main_config)
    section = ""
    for path in files:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                continue
            if section != "theme" or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in {"Current", "CursorTheme", "CursorSize", "Font", "ThemeDir"}:
                values[key.strip()] = value.strip()
    return values


def _copy_visual_tree(
    src: Path,
    dst: Path,
    *,
    trusted_roots: Iterable[Path] | None = None,
) -> bool:
    try:
        if not src.exists() or src.is_symlink() or path_is_sensitive(src):
            return False
        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        if src.is_dir():
            root = src.resolve()
            roots = [root]
            if trusted_roots is not None:
                for candidate in trusted_roots:
                    try:
                        resolved = candidate.resolve(strict=False)
                    except OSError:
                        continue
                    if resolved not in roots:
                        roots.append(resolved)
            dst.mkdir(parents=True, exist_ok=True)
            copied = False
            active_dirs: set[Path] = set()

            def trusted(path: Path) -> bool:
                for allowed in roots:
                    try:
                        path.relative_to(allowed)
                        return True
                    except ValueError:
                        continue
                return False

            def copy_dir(current: Path, target_root: Path) -> None:
                nonlocal copied
                try:
                    resolved_current = current.resolve(strict=True)
                except OSError:
                    return
                if resolved_current in active_dirs:
                    return
                if not trusted(resolved_current):
                    return
                active_dirs.add(resolved_current)
                try:
                    children = sorted(current.iterdir(), key=lambda item: item.name)
                except OSError:
                    active_dirs.discard(resolved_current)
                    return
                for item in children:
                    if path_is_sensitive(item):
                        continue
                    target = target_root / item.name
                    if item.is_symlink():
                        try:
                            resolved = item.resolve(strict=True)
                        except OSError:
                            continue
                        if not trusted(resolved):
                            # Never allow a theme symlink to pull arbitrary data
                            # from outside the explicitly trusted theme roots.
                            continue
                        if resolved.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                            copy_dir(resolved, target)
                        elif resolved.is_file():
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(resolved, target)
                            copied = True
                        continue
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        copy_dir(item, target)
                    elif item.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
                        copied = True
                active_dirs.discard(resolved_current)

            copy_dir(src, dst)
            return copied
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
        return False
    except OSError:
        return False


def _sddm_theme_candidates(settings: dict[str, str]) -> list[Path]:
    current = settings.get("Current", "").strip()
    if not current:
        return []
    roots: list[Path] = []
    custom = settings.get("ThemeDir", "").strip()
    if custom:
        custom_path = Path(custom).expanduser()
        if custom_path.is_absolute():
            roots.append(custom_path)
    roots.extend((Path("/usr/local/share/sddm/themes"), Path("/usr/share/sddm/themes")))
    result: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        candidate = root / current
        try:
            key = candidate.resolve(strict=False)
        except OSError:
            key = candidate
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _decode_sddm_asset_path(raw: str, *, theme_dir: Path, home: Path) -> Path | None:
    value = raw.strip().strip('"').strip("'")
    if not value or value.startswith(("qrc:", "data:", "http://", "https://")):
        return None
    if value.startswith("file://"):
        parsed = urlparse(value)
        if parsed.scheme != "file":
            return None
        value = unquote(parsed.path)
    else:
        value = unquote(value)
    if value.startswith("$HOME/"):
        candidate = home / value[len("$HOME/") :]
    elif value.startswith("~/"):
        candidate = home / value[2:]
    elif value.startswith("/"):
        candidate = Path(value)
    else:
        candidate = theme_dir / value
    try:
        return candidate.expanduser().resolve(strict=True)
    except OSError:
        return None


def _bundle_sddm_external_assets(theme_dir: Path, captured_theme: Path, home: Path) -> list[str]:
    """Make user-customized SDDM backgrounds self-contained.

    KDE's SDDM KCM stores user overrides in ``theme.conf.user`` next to the
    theme. The background value can be an absolute path into the user's
    Pictures directory. Copying only the theme directory therefore leaves a
    perfectly valid theme pointing at a file that is absent on the remastered
    system, commonly producing a blank/white greeter. Only concrete image
    references are promoted; browser state and unrelated home data remain out
    of scope.
    """
    if not captured_theme.is_dir():
        return []
    try:
        root = theme_dir.resolve(strict=True)
    except OSError:
        return []
    copied: list[str] = []
    config_names = {"theme.conf", "theme.conf.user"}
    metadata = captured_theme / "metadata.desktop"
    if metadata.is_file():
        try:
            section = ""
            for raw in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip().lower()
                    continue
                if section == "sddmgreetertheme" and "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip() == "ConfigFile":
                        rel = PurePosixPath(value.strip())
                        if not rel.is_absolute() and ".." not in rel.parts and rel.parts:
                            config_names.add(rel.as_posix())
                            config_names.add(rel.as_posix() + ".user")
        except OSError:
            pass
    config_files = sorted(
        path
        for path in captured_theme.rglob("*")
        if path.is_file()
        and (
            path.relative_to(captured_theme).as_posix() in config_names
            or path.name.endswith((".conf", ".conf.user", ".ini", ".ini.user"))
        )
    )
    for captured_config in config_files:
        try:
            relative = captured_config.relative_to(captured_theme)
            source_config = theme_dir / relative
            lines = captured_config.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, ValueError):
            continue
        rewritten: list[str] = []
        changed = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", ";")) or "=" not in line:
                rewritten.append(line)
                continue
            key, raw_value = line.split("=", 1)
            candidate = _decode_sddm_asset_path(raw_value, theme_dir=theme_dir, home=home)
            if candidate is None or not candidate.is_file() or path_is_sensitive(candidate):
                rewritten.append(line)
                continue
            if candidate.suffix.lower() not in WALLPAPER_IMAGE_EXTENSIONS:
                rewritten.append(line)
                continue
            try:
                if candidate.stat().st_size > 64 * 1024 * 1024:
                    rewritten.append(line)
                    continue
            except OSError:
                rewritten.append(line)
                continue

            try:
                inside_rel = candidate.relative_to(root)
            except ValueError:
                digest = sha256_file(candidate)[:12]
                safe_name = candidate.name.replace("/", "_") or "background"
                inside_rel = Path("suret-assets") / f"{digest}-{safe_name}"
                target = captured_theme / inside_rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, target)
                copied.append(inside_rel.as_posix())
            # Absolute paths inside the original theme are also rewritten: the
            # copied theme is renamed to ``suret-source`` on the target.
            replacement = inside_rel.as_posix()
            rewritten.append(f"{key}={replacement}")
            if raw_value.strip().strip('"').strip("'") != replacement:
                changed = True
        if changed:
            captured_config.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    return sorted(set(copied))


def _capture_system_visual_fidelity(
    output: Path,
    home: Path,
    component_details: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Capture non-personal, user-visible boot/login appearance.

    This intentionally excludes machine IDs, accounts and host-specific boot
    entries. Only theme assets and presentation-related settings are retained.
    """
    payload = output / "payload/system"
    visual: dict[str, object] = {"schema": 3, "grub": {}, "sddm": {}}

    grub = _read_grub_defaults()
    grub_meta: dict[str, object] = {"settings": grub}
    theme_raw = grub.get("GRUB_THEME", "")
    if theme_raw:
        theme = Path(theme_raw)
        theme_root = theme.parent if theme.is_file() else theme
        if _copy_visual_tree(theme_root, payload / "grub/theme"):
            grub_meta["theme_captured"] = True
            grub_meta["theme_file"] = theme.name if theme.is_file() else "theme.txt"
    bg_raw = grub.get("GRUB_BACKGROUND", "")
    if bg_raw:
        bg = Path(bg_raw)
        if bg.is_file() and _copy_visual_tree(bg, payload / "grub" / ("background" + bg.suffix.lower())):
            grub_meta["background_captured"] = True
            grub_meta["background_suffix"] = bg.suffix.lower()
    visual["grub"] = grub_meta

    sddm = _read_sddm_theme()
    sddm_meta: dict[str, object] = {"settings": sddm}
    current = sddm.get("Current", "")
    if current:
        candidates = _sddm_theme_candidates(sddm)
        theme_dir = next((x for x in candidates if x.is_dir()), None)
        captured_theme = payload / "sddm/theme"
        trusted_theme_roots: list[Path] = []
        configured_root = str(sddm.get("ThemeDir") or "").strip()
        if configured_root.startswith("/"):
            trusted_theme_roots.append(Path(configured_root))
        trusted_theme_roots.extend(
            [Path("/usr/local/share/sddm/themes"), Path("/usr/share/sddm/themes")]
        )
        if theme_dir and _copy_visual_tree(
            theme_dir, captured_theme, trusted_roots=trusted_theme_roots
        ):
            sddm_meta["theme_captured"] = True
            sddm_meta["source_theme"] = current
            sddm_meta["source_theme_dir"] = str(theme_dir.parent)
            bundled = _bundle_sddm_external_assets(theme_dir, captured_theme, home)
            if bundled:
                sddm_meta["external_assets"] = bundled

    # KDE's SDDM KCM can sync the user's Plasma presentation settings into
    # the dedicated sddm account. Record the active *direct* appearance
    # components so Native restore can promote the exact captured bundles to
    # system-readable locations before SDDM paints its first frame.
    direct_components: dict[str, dict[str, object]] = {}
    for component in component_details or []:
        kind = str(component.get("kind") or "")
        if not kind or component.get("inherited"):
            continue
        if kind not in {"icon-theme", "cursor-theme", "plasma-theme", "color-scheme", "look-and-feel"}:
            continue
        direct_components.setdefault(kind, {
            "name": str(component.get("name") or ""),
            "bundled": bool(component.get("bundled")),
            "bundle_root": component.get("bundle_root"),
        })
    if direct_components:
        sddm_meta["desktop_sync"] = direct_components
    visual["sddm"] = sddm_meta

    output.mkdir(parents=True, exist_ok=True)
    (output / "system-visual.json").write_text(json.dumps(visual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return visual


class CaptureError(RuntimeError):
    pass


def _source_brand_logo_candidates(source: dict[str, str | None]) -> list[Path]:
    tokens: list[str] = []
    for value in (source.get("distro_logo"), source.get("distro_id")):
        value = str(value or "").strip()
        if value and value not in tokens:
            tokens.append(value)
    for generic in ("distributor-logo", "start-here"):
        if generic not in tokens:
            tokens.append(generic)

    roots = (
        Path("/usr/share/pixmaps"),
        Path("/usr/share/icons/hicolor/scalable/apps"),
        Path("/usr/share/icons/hicolor/256x256/apps"),
        Path("/usr/share/icons/hicolor/128x128/apps"),
        Path("/usr/share/icons/hicolor/64x64/apps"),
        Path("/usr/share/icons/hicolor/48x48/apps"),
        Path("/usr/share/icons/breeze/apps/64"),
        Path("/usr/share/icons/breeze/apps/48"),
        Path("/usr/share/icons/breeze/apps/32"),
    )
    suffixes = (".svg", ".svgz", ".png", ".xpm")
    candidates: list[Path] = []
    for root in roots:
        for token in tokens:
            for name in (token, f"{token}-logo", f"logo-{token}"):
                for suffix in suffixes:
                    candidates.append(root / f"{name}{suffix}")
    return candidates


def _capture_source_branding(output: Path, source: dict[str, str | None]) -> dict[str, str | None]:
    branding = output / "branding"
    for candidate in _source_brand_logo_candidates(source):
        if not candidate.is_file():
            continue
        try:
            if candidate.stat().st_size > 8 * 1024 * 1024:
                continue
            branding.mkdir(parents=True, exist_ok=True)
            suffix = candidate.suffix.lower() or ".img"
            destination = branding / f"source-logo{suffix}"
            shutil.copy2(candidate, destination)
            source = dict(source)
            source["branding_logo"] = destination.relative_to(output).as_posix()
            source["branding_logo_source"] = str(candidate)
            return source
        except OSError:
            continue
    return source


def _safe_relative(path: Path, home: Path) -> Path:
    return path.resolve().relative_to(home.resolve())


def _rewrite_home(text: str, home: Path) -> tuple[str, int]:
    source = str(home)
    count = text.count(source)
    if not count:
        return text, 0
    return text.replace(source, "{{HOME}}"), count


def _portable_destination(dst: Path) -> str:
    parts = dst.parts
    for i in range(len(parts) - 1):
        if parts[i] == "payload" and parts[i + 1] == "home":
            relative = Path(*parts[i + 2 :])
            return "{{HOME}}" if str(relative) == "." else f"{{{{HOME}}}}/{relative.as_posix()}"
    return dst.as_posix()


def _copy_file(src: Path, dst: Path, home: Path, kind: str) -> CapturedFile:
    dst.parent.mkdir(parents=True, exist_ok=True)
    rewritten = 0
    sanitized = 0

    should_treat_as_text = src.name in SHELL_FILES or src.suffix.lower() in TEXT_EXTENSIONS or src.name.endswith("rc")
    if should_treat_as_text and src.stat().st_size <= 8 * 1024 * 1024:
        try:
            text = src.read_text(encoding="utf-8", errors="strict")
            # The assignment sanitizer is intentionally safe for generic
            # text/INI files too. This prevents TOKEN=/PASSWORD=/API_KEY= style
            # values from leaking through a non-shell config or .env file.
            result = sanitize_shell_text(text)
            text = result.text
            sanitized = result.redacted_lines
            text, rewritten = _rewrite_home(text, home)
            if src.suffix.lower() == ".desktop":
                desktop_result = sanitize_desktop_text(text)
                text = desktop_result.text
                sanitized += desktop_result.redacted_lines
                text = _rewrite_desktop_exec_compat(text)
            dst.write_text(text, encoding="utf-8")
            shutil.copymode(src, dst)
        except (UnicodeDecodeError, OSError):
            shutil.copy2(src, dst)
    else:
        shutil.copy2(src, dst)

    return CapturedFile(
        source=str(src).replace(str(home), "{{HOME}}", 1),
        destination=_portable_destination(dst),
        kind=kind,
        sha256=sha256_file(dst),
        rewritten_home_paths=rewritten,
        sanitized_lines=sanitized,
    )


def _rewrite_desktop_exec_compat(text: str) -> str:
    """Translate source-only launchers to commands available on the target.

    Labels and icons are preserved. Known web-app launchers are normalized by
    their visible name so browser-profile-specific commands do not break after
    migration. Unknown commands are deliberately left untouched.
    """
    primary_name = ""
    for raw in text.splitlines():
        if raw.startswith("Name="):
            primary_name = raw.split("=", 1)[1].strip().casefold()
            break
    web_replacement = {
        "whatsapp web": "xdg-open https://web.whatsapp.com/",
        "chatgpt": "xdg-open https://chatgpt.com/",
    }.get(primary_name)

    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        newline = line[len(stripped) :]
        if not stripped.startswith("Exec="):
            lines.append(line)
            continue
        command = stripped.split("=", 1)[1].strip()
        executable = command.split(None, 1)[0] if command else ""
        replacement = web_replacement
        if replacement is None:
            replacement = DESKTOP_EXEC_COMPAT_REPLACEMENTS.get(executable)
        if replacement is None and executable:
            replacement = DESKTOP_EXEC_COMPAT_REPLACEMENTS.get(Path(executable).name)
        if replacement is None:
            lines.append(line)
            continue
        # Keep a reversible copy of the source Exec contract. Generic mode
        # still receives the portable replacement, while Native ISO mode can
        # restore distro-native launchers (for example pardus-about) when the
        # base ISO is the same distribution as the captured profile. Base64
        # avoids Desktop Entry escaping ambiguities and the command has already
        # had the source home path rewritten to {{HOME}} above.
        encoded = base64.urlsafe_b64encode(command.encode("utf-8")).decode("ascii")
        lines.append(f"Exec={replacement}{newline}")
        lines.append(f"X-Suret-Original-Exec-B64={encoded}{newline}")
    return "".join(lines)


def _copy_tree(src: Path, payload_home: Path, home: Path, kind: str, excluded: list[str]) -> list[CapturedFile]:
    captured: list[CapturedFile] = []
    for item in src.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        if path_is_sensitive(item):
            excluded.append(str(item).replace(str(home), "{{HOME}}", 1))
            continue
        try:
            relative = _safe_relative(item, home)
        except ValueError:
            continue
        # Avoid accidentally embedding giant local files into the profile.
        try:
            if item.stat().st_size > 64 * 1024 * 1024:
                excluded.append(f"{str(item).replace(str(home), '{{HOME}}', 1)} (over 64 MiB)")
                continue
        except OSError:
            continue
        captured.append(_copy_file(item, payload_home / relative, home, kind))
    return captured


def _favorite_stats_only(text: str, home: Path) -> str:
    """Keep only Kickoff favorites ordering groups from KActivities stats.

    The source file can contain usage/statistics state unrelated to desktop
    fidelity.  Favorites ordering is user-visible, so preserve those sections
    while deliberately excluding history-like data.
    """
    chunks: list[str] = []
    current: list[str] = []
    keep = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if keep and current:
                chunks.extend(current)
                chunks.append("")
            section = stripped[1:-1]
            keep = section.startswith("Favorites-")
            current = [line] if keep else []
            continue
        if keep:
            current.append(line)
    if keep and current:
        chunks.extend(current)
    result = "\n".join(chunks).rstrip() + ("\n" if chunks else "")
    return result.replace(str(home), "{{HOME}}")


def _capture_kickoff_favorites_state(
    home: Path,
    payload_home: Path,
) -> list[CapturedFile]:
    """Capture only the state required to reproduce Kickoff favorites.

    Membership lives in the KActivities SQLite ResourceLink table while the
    display order lives in kactivitymanagerd-statsrc.  The database is backed up
    through SQLite, stripped of all non-favorite activity/history rows, and
    VACUUMed so deleted history is not left in free pages.
    """
    captured: list[CapturedFile] = []

    stats_src = home / ".config/kactivitymanagerd-statsrc"
    if stats_src.is_file():
        try:
            sanitized = _favorite_stats_only(
                stats_src.read_text(encoding="utf-8", errors="replace"), home
            )
        except OSError:
            sanitized = ""
        if sanitized:
            stats_dst = payload_home / ".config/kactivitymanagerd-statsrc"
            stats_dst.parent.mkdir(parents=True, exist_ok=True)
            stats_dst.write_text(sanitized, encoding="utf-8")
            try:
                shutil.copymode(stats_src, stats_dst)
            except OSError:
                pass
            captured.append(
                CapturedFile(
                    source="{{HOME}}/.config/kactivitymanagerd-statsrc",
                    destination="{{HOME}}/.config/kactivitymanagerd-statsrc",
                    kind="kickoff-favorites-order",
                    sha256=sha256_file(stats_dst),
                )
            )

    db_src = home / ".local/share/kactivitymanagerd/resources/database"
    if db_src.is_file():
        db_dst = payload_home / ".local/share/kactivitymanagerd/resources/database"
        db_dst.parent.mkdir(parents=True, exist_ok=True)
        source = None
        target = None
        try:
            source = sqlite3.connect(f"file:{db_src}?mode=ro", uri=True, timeout=2)
            target = sqlite3.connect(db_dst)
            source.backup(target)
            tables = [
                str(row[0])
                for row in target.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                if table == "ResourceLink":
                    target.execute(
                        f"DELETE FROM {quoted} WHERE initiatingAgent <> ? OR initiatingAgent IS NULL",
                        (KACTIVITY_FAVORITES_AGENT,),
                    )
                elif table != "SchemaInfo":
                    target.execute(f"DELETE FROM {quoted}")
            target.commit()
            target.execute("VACUUM")
            target.commit()
        except (OSError, sqlite3.Error):
            if target is not None:
                target.close()
                target = None
            db_dst.unlink(missing_ok=True)
        finally:
            if source is not None:
                source.close()
            if target is not None:
                target.close()

        if db_dst.is_file():
            try:
                shutil.copymode(db_src, db_dst)
            except OSError:
                pass
            captured.append(
                CapturedFile(
                    source="{{HOME}}/.local/share/kactivitymanagerd/resources/database",
                    destination="{{HOME}}/.local/share/kactivitymanagerd/resources/database",
                    kind="kickoff-favorites-membership",
                    sha256=sha256_file(db_dst),
                )
            )
    return captured



def _runtime_plasma_wallpaper_state(home: Path) -> list[dict[str, object]]:
    """Read the wallpaper state from the running Plasma shell when possible.

    The on-disk applet config may lag behind the wallpaper currently visible on
    screen. Plasma's supported scripting API exposes each live Desktop
    containment, its wallpaper plugin and the current Image/SlidePaths values.
    Failure is non-fatal so headless scans still fall back to config parsing.
    """
    qdbus = next(
        (tool for name in ("qdbus6", "qdbus-qt6", "qdbus") if (tool := shutil.which(name))),
        None,
    )
    if not qdbus:
        return []
    script = (
        'var out=[]; var aid=currentActivity(); var ds=desktopsForActivity(aid); '
        'if (!ds || !ds.length) ds=desktops(); '
        'for (var i=0; i<ds.length; ++i) {'
        ' var d=ds[i]; var p=d.wallpaperPlugin;'
        ' d.currentConfigGroup=["Wallpaper",p,"General"];'
        ' out.push({id:d.id,screen:(typeof d.screen === \"undefined\" ? -1 : d.screen),plugin:p,image:d.readConfig("Image",""),slidePaths:d.readConfig("SlidePaths",""),activity:aid});'
        '} JSON.stringify(out);'
    )
    try:
        proc = subprocess.run(
            [qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    output = proc.stdout.strip()
    candidates = [output] + [line.strip() for line in output.splitlines() if line.strip().startswith("[")]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, list):
            continue
        result: list[dict[str, object]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                containment_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            try:
                screen = int(item.get("screen", -1))
            except (TypeError, ValueError):
                screen = -1
            result.append(
                {
                    "id": containment_id,
                    "screen": screen,
                    "plugin": str(item.get("plugin") or ""),
                    "image": str(item.get("image") or ""),
                    "slidePaths": str(item.get("slidePaths") or ""),
                }
            )
        return result
    return []


def _runtime_wallpaper_files(home: Path, states: list[dict[str, object]]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for state in states:
        raw_values = [str(state.get("image") or "")]
        raw_values.extend(
            str(state.get("slidePaths") or "").replace(";", ",").split(",")
        )
        for raw in raw_values:
            path = _normalize_local_config_path(raw, home)
            if path is not None and path not in seen:
                seen.add(path)
                result.append(path)
    return result


def _portable_wallpaper_target(src: Path, home: Path, replacements: dict[str, str]) -> str | None:
    try:
        relative = src.resolve().relative_to(home.resolve())
    except (OSError, ValueError):
        try:
            return replacements.get(str(src.resolve()))
        except OSError:
            return None
    return f"{{{{HOME}}}}/{relative.as_posix()}"


def _runtime_primary_visible_wallpaper(
    home: Path,
    states: list[dict[str, object]],
    replacements: dict[str, str],
) -> str | None:
    """Return the wallpaper actually visible on the primary Plasma screen.

    Reading the first ``Image=`` entry from plasma's persisted config is not
    sufficient: stale/dormant containments can appear before the active screen.
    Runtime Plasma state is therefore authoritative when available. Screen 0 is
    preferred, followed by other numbered screens and finally unknown-screen
    containments in their runtime order.
    """
    ranked: list[tuple[tuple[int, int, int], str]] = []
    for index, state in enumerate(states):
        image = _normalize_local_config_path(str(state.get("image") or ""), home)
        if image is None or not image.is_file():
            continue
        target = _portable_wallpaper_target(image, home, replacements)
        if not target:
            continue
        try:
            screen = int(state.get("screen", -1))
        except (TypeError, ValueError):
            screen = -1
        if screen == 0:
            rank = (0, 0, index)
        elif screen >= 0:
            rank = (1, screen, index)
        else:
            rank = (2, 9999, index)
        ranked.append((rank, target))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def _apply_runtime_wallpaper_state(
    payload_home: Path,
    home: Path,
    states: list[dict[str, object]],
    replacements: dict[str, str],
    captured_configs: list[CapturedFile],
) -> None:
    """Apply live Plasma wallpaper state without changing the wallpaper plugin.

    Older Suret releases forced slideshow containments to ``org.kde.image`` so
    the first frame was deterministic. That preserved one picture but destroyed
    the user's slideshow behavior. Runtime state is now used only to refresh
    the active containment/plugin/path values while preserving slideshow mode,
    interval/order settings and the complete captured collection.
    """
    usable: dict[int, dict[str, object]] = {}
    for state in states:
        try:
            containment_id = int(state.get("id"))
        except (TypeError, ValueError):
            continue
        plugin = str(state.get("plugin") or "").strip()
        if not plugin:
            continue
        entry: dict[str, object] = {"plugin": plugin}
        image = _normalize_local_config_path(str(state.get("image") or ""), home)
        if image is not None and image.is_file():
            target = _portable_wallpaper_target(image, home, replacements)
            if target:
                entry["Image"] = "file://" + target

        slide_targets: list[str] = []
        for raw in str(state.get("slidePaths") or "").replace(";", ",").split(","):
            path = _normalize_local_config_path(raw, home)
            if path is None:
                continue
            target = _portable_wallpaper_target(path, home, replacements)
            if target:
                slide_targets.append("file://" + target)
        if slide_targets:
            entry["SlidePaths"] = ",".join(dict.fromkeys(slide_targets))

        if "Image" in entry or "SlidePaths" in entry or plugin != "org.kde.image":
            usable[containment_id] = entry
    if not usable:
        return

    config = payload_home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not config.is_file():
        return
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return

    new_lines: list[str] = []
    section = ""
    active_id: int | None = None
    wallpaper_section_for: int | None = None
    section_keys: set[str] = set()
    containment_had_plugin = False
    changed = False

    def finish_section() -> None:
        nonlocal changed
        if wallpaper_section_for not in usable:
            return
        entry = usable[wallpaper_section_for]
        for key in ("Image", "SlidePaths"):
            value = entry.get(key)
            if value and key not in section_keys:
                new_lines.append(f"{key}={value}")
                changed = True

    def finish_containment() -> None:
        nonlocal changed
        if active_id not in usable or containment_had_plugin:
            return
        if section == f"[Containments][{active_id}]":
            plugin = str(usable[active_id]["plugin"])
            new_lines.append(f"wallpaperplugin={plugin}")
            changed = True

    containment_re = re.compile(r"^\[Containments\]\[(\d+)\](.*)$")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            finish_section()
            finish_containment()
            section = stripped
            section_keys = set()
            containment_had_plugin = False
            wallpaper_section_for = None
            active_id = None
            match = containment_re.match(section)
            if match:
                active_id = int(match.group(1))
                suffix = match.group(2)
                if active_id in usable and "[Wallpaper]" in suffix and suffix.endswith("[General]"):
                    wallpaper_section_for = active_id
                    plugin = str(usable[active_id]["plugin"])
                    replacement = re.sub(
                        r"\[Wallpaper\]\[[^\]]+\]\[General\]$",
                        f"[Wallpaper][{plugin}][General]",
                        section,
                    )
                    if replacement != section:
                        line = replacement
                        section = replacement
                        changed = True
            new_lines.append(line)
            continue

        if active_id in usable and section == f"[Containments][{active_id}]" and "=" in line:
            key, _value = line.split("=", 1)
            if key.strip().lower() == "wallpaperplugin":
                replacement = f"wallpaperplugin={usable[active_id]['plugin']}"
                new_lines.append(replacement)
                containment_had_plugin = True
                if line != replacement:
                    changed = True
                continue

        if wallpaper_section_for in usable and "=" in line:
            key, _value = line.split("=", 1)
            key = key.strip()
            if key in {"Image", "SlidePaths"} and usable[wallpaper_section_for].get(key):
                replacement = f"{key}={usable[wallpaper_section_for][key]}"
                new_lines.append(replacement)
                section_keys.add(key)
                if line != replacement:
                    changed = True
                continue
        new_lines.append(line)

    finish_section()
    finish_containment()
    if not changed:
        return
    config.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    destination = "{{HOME}}/.config/plasma-org.kde.plasma.desktop-appletsrc"
    for item in captured_configs:
        if item.destination == destination:
            item.sha256 = sha256_file(config)
            break


def _slideshow_initial_overrides(home: Path) -> dict[str, str]:
    """Choose the best approximation of the currently visible slideshow image.

    Plasma 6 may leave the persisted ``Image=`` value one slide behind until
    plasmashell exits.  Filesystem access time gives us a useful local signal for
    the image most recently rendered, and unlike a screenshot it does not bake
    panels/icons into the wallpaper.  This is used only for slideshow groups;
    the complete slide collection is still captured separately.
    """
    config = home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not config.is_file():
        return {}
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}

    groups: dict[str, dict[str, str]] = {}
    section = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
            groups.setdefault(section, {})
            continue
        if section and "=" in line:
            key, value = line.split("=", 1)
            groups[section][key.strip()] = value.strip()

    overrides: dict[str, str] = {}
    home_resolved = home.resolve()
    for section, values in groups.items():
        if "[Wallpaper][org.kde.slideshow][General]" not in section:
            continue
        raw_paths = values.get("SlidePaths", "").replace(";", ",").split(",")
        candidates: list[Path] = []
        for raw in raw_paths:
            path = _normalize_local_config_path(raw, home)
            if path is None:
                continue
            if path.is_file() and path.suffix.lower() in WALLPAPER_IMAGE_EXTENSIONS:
                candidates.append(path)
                continue
            if not path.is_dir():
                continue
            try:
                for item in path.rglob("*"):
                    if (
                        item.is_file()
                        and not item.is_symlink()
                        and item.suffix.lower() in WALLPAPER_IMAGE_EXTENSIONS
                    ):
                        candidates.append(item)
            except OSError:
                continue
        if not candidates:
            continue

        def recency(path: Path) -> tuple[int, int, str]:
            try:
                stat = path.stat()
                return stat.st_atime_ns, stat.st_mtime_ns, str(path)
            except OSError:
                return 0, 0, str(path)

        chosen = max(candidates, key=recency)
        try:
            relative = chosen.resolve().relative_to(home_resolved)
        except (OSError, ValueError):
            # External slideshow directories are still captured, but without a
            # portable path map at this early phase it is safer not to guess.
            continue
        overrides[section] = f"file://{{{{HOME}}}}/{relative.as_posix()}"
    return overrides


def _apply_slideshow_initial_overrides(
    payload_home: Path,
    overrides: dict[str, str],
    captured_configs: list[CapturedFile],
) -> None:
    """Seed slideshow desktops with the source-visible image without disabling them.

    The copied ``Image=`` value can point at a stale distro wallpaper even when
    ``SlidePaths`` is correct. Set a captured slide as the initial image, but
    keep ``org.kde.slideshow`` and all slideshow timing/order settings intact.
    """
    if not overrides:
        return
    config = payload_home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not config.is_file():
        return
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return

    new_lines: list[str] = []
    section = ""
    section_had_image = False
    changed = False

    def finish_section() -> None:
        nonlocal changed
        if section in overrides and not section_had_image:
            new_lines.append(f"Image={overrides[section]}")
            changed = True

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            finish_section()
            section = stripped
            section_had_image = False
            new_lines.append(line)
            continue

        if section in overrides and "=" in line:
            key, _value = line.split("=", 1)
            if key.strip() == "Image":
                replacement = f"Image={overrides[section]}"
                new_lines.append(replacement)
                section_had_image = True
                if line != replacement:
                    changed = True
                continue
        new_lines.append(line)

    finish_section()
    if not changed:
        return
    config.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    destination = "{{HOME}}/.config/plasma-org.kde.plasma.desktop-appletsrc"
    for item in captured_configs:
        if item.destination == destination:
            item.sha256 = sha256_file(config)
            break



def _captured_visible_wallpaper(payload_home: Path) -> str | None:
    """Return the portable wallpaper path from the already-rewritten profile.

    The returned value is a ``{{HOME}}/...`` path, not a file URL.  Reading it
    from the copied config means this reflects all relocation and live-session
    wallpaper repairs that happened during capture.
    """
    config = payload_home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not config.is_file():
        return None
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "Image":
            continue
        value = unquote(value.strip())
        if value.startswith("file://"):
            value = value[len("file://") :]
        if not value.startswith("{{HOME}}/"):
            continue
        relative = value[len("{{HOME}}/") :]
        candidate = payload_home / relative
        if candidate.is_file():
            return "{{HOME}}/" + relative
    return None


def _captured_slideshow_state(
    payload_home: Path,
    runtime_states: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    config = payload_home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    result: dict[str, object] = {"active": False, "paths": [], "containments": 0, "entries": []}
    if not config.is_file():
        return result
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result

    runtime_screen: dict[int, int] = {}
    for state in runtime_states or []:
        try:
            runtime_screen[int(state.get("id"))] = int(state.get("screen", -1))
        except (TypeError, ValueError):
            continue

    groups: dict[str, dict[str, str]] = {}
    section = ""
    plugin_by_containment: dict[int, str] = {}
    section_re = re.compile(r"^\[Containments\]\[(\d+)\](.*)$")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
            groups.setdefault(section, {})
            continue
        if section and "=" in line:
            key, value = line.split("=", 1)
            groups[section][key.strip()] = value.strip()
            match = section_re.match(section)
            if match and match.group(2) == "" and key.strip().lower() == "wallpaperplugin":
                plugin_by_containment[int(match.group(1))] = value.strip()

    paths: list[str] = []
    entries: list[dict[str, object]] = []
    for group, settings in groups.items():
        match = section_re.match(group)
        if not match or not group.endswith("[Wallpaper][org.kde.slideshow][General]"):
            continue
        cid = int(match.group(1))
        plugin = plugin_by_containment.get(cid, "org.kde.slideshow")
        if plugin != "org.kde.slideshow":
            continue
        portable_settings: dict[str, str] = {}
        for key, value in settings.items():
            if not key or len(key) > 128 or any(ch in key for ch in "\r\n\0"):
                continue
            if len(value) > 16384 or any(ch in value for ch in "\r\0"):
                continue
            portable_settings[key] = value
        raw_paths = portable_settings.get("SlidePaths", "")
        entry_paths: list[str] = []
        for raw in raw_paths.replace(";", ",").split(","):
            token = unquote(raw.strip())
            if token.startswith("file://"):
                token = token[7:]
            if token and token not in paths:
                paths.append(token)
            if token and token not in entry_paths:
                entry_paths.append(token)
        entries.append({
            "containment_id": cid,
            "screen": runtime_screen.get(cid, -1),
            "plugin": "org.kde.slideshow",
            "paths": entry_paths,
            "settings": portable_settings,
        })

    result["active"] = bool(entries)
    result["paths"] = paths
    result["containments"] = len(entries)
    result["entries"] = entries
    return result


def _copy_external_tree(
    src: Path,
    destination_root: Path,
    home: Path,
    kind: str,
    excluded: list[str],
) -> list[CapturedFile]:
    captured: list[CapturedFile] = []
    for item in src.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        if path_is_sensitive(item):
            excluded.append(str(item))
            continue
        try:
            if item.stat().st_size > 64 * 1024 * 1024:
                excluded.append(f"{item} (over 64 MiB)")
                continue
        except OSError:
            continue
        relative = item.relative_to(src)
        captured.append(_copy_file(item, destination_root / relative, home, kind))
    return captured


def _mark_required_package(
    packages: list[Package],
    package_index: dict[tuple[str, str], Package],
    provider: str,
    package_name: str,
    reason: str,
) -> Package:
    key = (provider, package_name)
    pkg = package_index.get(key)
    if pkg is None:
        pkg = Package(
            name=package_name,
            provider=provider,
            category="system",
            required_for_appearance=True,
            reason=reason,
            installer_visible=True,
            visibility_reason="Required by captured desktop appearance.",
        )
        packages.append(pkg)
        package_index[key] = pkg
    else:
        pkg.required_for_appearance = True
        pkg.reason = reason
        pkg.installer_visible = True
        pkg.visibility_reason = "Required by captured desktop appearance."
    return pkg


def _copy_component(
    src: Path,
    payload_home: Path,
    target_relative: Path,
    home: Path,
    excluded: list[str],
    kind: str,
) -> list[CapturedFile]:
    """Copy an active appearance component with safe symlink dereferencing.

    Third-party KDE icon/theme packs downloaded through KNewStuff frequently
    contain many relative symlinks (Tela is a common example). The generic
    profile copier deliberately ignores symlinks because profiles must remain
    inert regular-file bundles. For *appearance components* we can preserve the
    visual result safely by dereferencing a link only when its final target stays
    inside an allow-listed appearance root. The target is copied as a regular
    file/directory at the link's visible path, so the resulting profile itself
    still contains no symlinks.
    """
    destination = payload_home / target_relative

    roots_by_kind: dict[str, tuple[Path, ...]] = {
        "icon-theme": (
            home / ".local/share/icons",
            home / ".icons",
            Path("/usr/local/share/icons"),
            Path("/usr/share/icons"),
        ),
        "cursor-theme": (
            home / ".local/share/icons",
            home / ".icons",
            Path("/usr/local/share/icons"),
            Path("/usr/share/icons"),
        ),
        "plasma-theme": (
            home / ".local/share/plasma/desktoptheme",
            Path("/usr/local/share/plasma/desktoptheme"),
            Path("/usr/share/plasma/desktoptheme"),
        ),
        "look-and-feel": (
            home / ".local/share/plasma/look-and-feel",
            Path("/usr/local/share/plasma/look-and-feel"),
            Path("/usr/share/plasma/look-and-feel"),
        ),
        "splash-theme": (
            home / ".local/share/plasma/look-and-feel",
            Path("/usr/local/share/plasma/look-and-feel"),
            Path("/usr/share/plasma/look-and-feel"),
        ),
        "window-decoration": (
            home / ".local/share/aurorae/themes",
            home / ".local/share/kwin/decorations",
            Path("/usr/local/share/aurorae/themes"),
            Path("/usr/share/aurorae/themes"),
            Path("/usr/local/share/kwin/decorations"),
            Path("/usr/share/kwin/decorations"),
        ),
        "gtk-theme": (
            home / ".local/share/themes",
            home / ".themes",
            Path("/usr/local/share/themes"),
            Path("/usr/share/themes"),
        ),
        "kvantum-theme": (
            home / ".config/Kvantum",
            home / ".local/share/Kvantum",
            Path("/usr/local/share/Kvantum"),
            Path("/usr/share/Kvantum"),
        ),
        "kwin-script": (
            home / ".local/share/kwin/scripts",
            Path("/usr/local/share/kwin/scripts"),
            Path("/usr/share/kwin/scripts"),
        ),
        "kwin-effect": (
            home / ".local/share/kwin/effects",
            Path("/usr/local/share/kwin/effects"),
            Path("/usr/share/kwin/effects"),
        ),
        "color-scheme": (
            home / ".local/share/color-schemes",
            Path("/usr/local/share/color-schemes"),
            Path("/usr/share/color-schemes"),
        ),
    }
    configured_roots = list(roots_by_kind.get(kind, ()))
    # The resolver normally returns entries under the known XDG/system roots.
    # Keep the concrete component parent as a narrow additional trust root so
    # distro-specific/KNewStuff-compatible locations can still preserve sibling
    # theme symlinks without allowing links to escape into arbitrary home data.
    configured_roots.append(src.parent)
    allowed_roots = tuple(dict.fromkeys(root.resolve(strict=False) for root in configured_roots))

    def within_allowed(path: Path) -> bool:
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return False
        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    captured: list[CapturedFile] = []

    def copy_node(node: Path, target: Path, stack: tuple[Path, ...]) -> None:
        try:
            resolved = node.resolve(strict=True)
        except OSError:
            excluded.append(f"{node} (broken appearance symlink/path)")
            return
        if not within_allowed(resolved):
            excluded.append(f"{node} (appearance symlink escapes trusted roots)")
            return
        if path_is_sensitive(resolved):
            excluded.append(str(node).replace(str(home), "{{HOME}}", 1))
            return
        if resolved in stack:
            excluded.append(f"{node} (appearance symlink loop)")
            return

        if resolved.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            try:
                children = sorted(resolved.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                return
            next_stack = stack + (resolved,)
            for child in children:
                copy_node(child, target / child.name, next_stack)
            return
        if not resolved.is_file():
            excluded.append(f"{node} (unsupported appearance object)")
            return
        try:
            if resolved.stat().st_size > 64 * 1024 * 1024:
                excluded.append(f"{node} (over 64 MiB)")
                return
        except OSError:
            return
        captured.append(_copy_file(resolved, target, home, "appearance-component"))

    if src.exists() or src.is_symlink():
        copy_node(src, destination, ())
    return captured


def _portable_home_path(path: Path, home: Path) -> str:
    try:
        rel = path.resolve().relative_to(home.resolve())
    except (OSError, ValueError):
        return path.as_posix()
    return f"{{{{HOME}}}}/{rel.as_posix()}"


def _dedupe_captured(items: list[CapturedFile]) -> list[CapturedFile]:
    by_destination: dict[str, CapturedFile] = {}
    for item in items:
        by_destination[item.destination] = item
    return [by_destination[key] for key in sorted(by_destination)]


def _copy_local_entry(
    src: Path,
    payload_home: Path,
    home: Path,
    kind: str,
    excluded: list[str],
) -> list[CapturedFile]:
    if src.is_dir():
        return _copy_tree(src, payload_home, home, kind, excluded)
    if src.is_file():
        relative = _safe_relative(src, home)
        return [_copy_file(src, payload_home / relative, home, kind)]
    return []



def _xdg_desktop_directory(home: Path) -> Path:
    """Return the user's visible XDG desktop directory.

    KDE installations may localize this directory (for example ``Masaüstü``)
    instead of using ``Desktop``.  The setting is kept in
    ``~/.config/user-dirs.dirs`` and may use either ``$HOME`` or an absolute
    home path.
    """
    config = home / ".config/user-dirs.dirs"
    if config.is_file():
        try:
            text = config.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("XDG_DESKTOP_DIR="):
                continue
            raw = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            raw = raw.replace("${HOME}", str(home)).replace("$HOME", str(home))
            if raw.startswith("~/"):
                raw = str(home / raw[2:])
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = home / candidate
            try:
                resolved = candidate.resolve(strict=False)
                resolved.relative_to(home.resolve())
            except (OSError, ValueError):
                break
            return resolved
    for name in ("Desktop", "Masaüstü", "Masaustu"):
        candidate = home / name
        if candidate.is_dir():
            return candidate
    return home / "Desktop"


def _visible_desktop_launchers(home: Path) -> list[Path]:
    """Return visible launcher/control files from the XDG desktop directory.

    Personal documents are deliberately excluded: the ISO profile should
    reproduce what the user sees without accidentally embedding arbitrary
    desktop documents.  Application/link launchers and ``.directory`` metadata
    are part of the desktop UI and are safe to reproduce.
    """
    desktop = _xdg_desktop_directory(home)
    if not desktop.is_dir():
        return []
    allowed = {".desktop", ".directory", ".url"}
    result: list[Path] = []
    try:
        entries = sorted(desktop.iterdir(), key=lambda item: item.name.casefold())
    except OSError:
        return []
    for entry in entries:
        if entry.name.startswith(".") and entry.name != ".directory":
            continue
        suffix = entry.suffix.lower()
        if suffix not in allowed:
            continue
        if entry.is_symlink():
            try:
                target = entry.resolve(strict=True)
            except OSError:
                continue
            if target.is_file() and not path_is_sensitive(target):
                result.append(entry)
            continue
        if entry.is_file() and not path_is_sensitive(entry):
            result.append(entry)
    return result



def _plasma_desktop_launcher_references(home: Path) -> list[Path]:
    """Resolve concrete .desktop files referenced by Plasma desktop applets.

    An icon applet can point directly at a source-distro launcher under
    /usr/share/applications.  Copying the applet configuration alone leaves a
    broken or generic icon on another distribution.
    """
    config = home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not config.is_file():
        return []
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    pattern = re.compile(
        r"(?P<path>(?:file://)?(?:~|\$HOME|/)[^\n\r'\"]+?\.desktop)", re.I
    )
    found: list[Path] = []
    seen: set[Path] = set()
    for match in pattern.finditer(text):
        resolved = _normalize_local_config_path(match.group("path"), home)
        if resolved is None or not resolved.is_file() or resolved in seen:
            continue
        if path_is_sensitive(resolved):
            continue
        seen.add(resolved)
        found.append(resolved)
    return found


def _copy_visible_desktop_launcher(
    launcher: Path,
    payload_home: Path,
    home: Path,
) -> CapturedFile | None:
    desktop = _xdg_desktop_directory(home)
    try:
        relative = launcher.relative_to(home)
    except ValueError:
        return None
    destination = payload_home / relative
    source = launcher
    if launcher.is_symlink():
        try:
            source = launcher.resolve(strict=True)
        except OSError:
            return None
    captured = _copy_file(source, destination, home, "desktop-surface-launcher")
    # Preserve the visible filename even when the source was a symlink into
    # /usr/share/applications. _copy_file records the resolved source path but
    # the destination remains the localized desktop directory.
    return captured

def _appearance_library_entries(
    home: Path,
    active_components: list[dict[str, object]] | None = None,
) -> list[tuple[str, Path, Path]]:
    """Return user-installed/manual appearance packages visible in KDE settings.

    Active-only mode still needs to reproduce the *visible appearance library*:
    KDE Store installs usually live in user XDG roots, while install scripts can
    place themes under /usr/local or unpackaged /usr/share entries. Distro-owned
    defaults are already supplied by the Native Pardus base and are not copied.
    """
    specs: list[tuple[str, Path, Path, bool]] = [
        ("icon-theme", home / ".local/share/icons", Path(".local/share/icons"), True),
        ("icon-theme", home / ".icons", Path(".local/share/icons"), True),
        ("plasma-theme", home / ".local/share/plasma/desktoptheme", Path(".local/share/plasma/desktoptheme"), True),
        ("look-and-feel", home / ".local/share/plasma/look-and-feel", Path(".local/share/plasma/look-and-feel"), True),
        ("color-scheme", home / ".local/share/color-schemes", Path(".local/share/color-schemes"), True),
        ("window-decoration", home / ".local/share/aurorae/themes", Path(".local/share/aurorae/themes"), True),
        ("window-decoration", home / ".local/share/kwin/decorations", Path(".local/share/kwin/decorations"), True),
        ("gtk-theme", home / ".local/share/themes", Path(".local/share/themes"), True),
        ("gtk-theme", home / ".themes", Path(".local/share/themes"), True),
        ("kvantum-theme", home / ".local/share/Kvantum", Path(".local/share/Kvantum"), True),
        ("kvantum-theme", home / ".config/Kvantum", Path(".config/Kvantum"), True),
        ("icon-theme", Path("/usr/local/share/icons"), Path(".local/share/icons"), True),
        ("plasma-theme", Path("/usr/local/share/plasma/desktoptheme"), Path(".local/share/plasma/desktoptheme"), True),
        ("look-and-feel", Path("/usr/local/share/plasma/look-and-feel"), Path(".local/share/plasma/look-and-feel"), True),
        ("color-scheme", Path("/usr/local/share/color-schemes"), Path(".local/share/color-schemes"), True),
        ("window-decoration", Path("/usr/local/share/aurorae/themes"), Path(".local/share/aurorae/themes"), True),
        ("gtk-theme", Path("/usr/local/share/themes"), Path(".local/share/themes"), True),
        # /usr/share entries are copied only when no distro package owns them.
        ("icon-theme", Path("/usr/share/icons"), Path(".local/share/icons"), False),
        ("plasma-theme", Path("/usr/share/plasma/desktoptheme"), Path(".local/share/plasma/desktoptheme"), False),
        ("look-and-feel", Path("/usr/share/plasma/look-and-feel"), Path(".local/share/plasma/look-and-feel"), False),
        ("color-scheme", Path("/usr/share/color-schemes"), Path(".local/share/color-schemes"), False),
        ("window-decoration", Path("/usr/share/aurorae/themes"), Path(".local/share/aurorae/themes"), False),
        ("gtk-theme", Path("/usr/share/themes"), Path(".local/share/themes"), False),
    ]
    family_prefixes: set[str] = set()
    for component in active_components or []:
        raw = str(component.get("name") or "").strip().casefold()
        if not raw:
            continue
        first = re.split(r"[-_.\s]+", raw, maxsplit=1)[0]
        normalized = re.sub(r"[^a-z0-9]+", "", first.casefold())
        if len(normalized) >= 3:
            family_prefixes.add(normalized)

    result: list[tuple[str, Path, Path]] = []
    seen_targets: set[Path] = set()
    for kind, root, target_root, always in specs:
        if not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if kind == "color-scheme":
                if not entry.is_file() or entry.suffix != ".colors":
                    continue
            elif not (entry.is_dir() or entry.is_symlink()):
                continue
            # hicolor contains application-export icons and is already captured
            # by the dedicated launcher/icon path; avoid duplicating it here.
            if kind == "icon-theme" and entry.name == "hicolor":
                continue
            if not always:
                # System /usr/share can contain hundreds of distro themes. Only
                # inspect manual packages that belong to a family currently in
                # use (e.g. Tela-* / Nordic-*); the native base already owns the
                # rest. This keeps capture deterministic and fast.
                normalized_entry = re.sub(r"[^a-z0-9]+", "", (entry.stem if entry.is_file() else entry.name).casefold())
                if not family_prefixes or not any(normalized_entry.startswith(prefix) for prefix in family_prefixes):
                    continue
                probe = ownership_probe(entry)
                if package_owner(probe) is not None:
                    continue
            target = target_root / entry.name
            if target in seen_targets:
                continue
            seen_targets.add(target)
            result.append((kind, entry, target))
    return result


def _active_only_always_roots(home: Path) -> list[Path]:
    """User state retained even when inactive theme collections are pruned.

    These roots are either difficult to map safely to a single active package or
    represent small user-authored state that is part of the desktop workflow.
    """
    candidates = [
        home / ".local/share/fonts",
        home / ".fonts",
        home / ".local/share/applications",
        home / ".local/share/kwin/tabbox",
        home / ".local/share/icons/hicolor",
    ]
    return [path for path in candidates if path.exists()]


def _reference_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root.is_file():
            if root not in seen:
                seen.add(root)
                files.append(root)
            continue
        if not root.is_dir():
            continue
        for item in root.rglob("*"):
            if not item.is_file() or item.is_symlink() or path_is_sensitive(item):
                continue
            if item.suffix.lower() in TEXT_EXTENSIONS or item.name.endswith("rc"):
                if item not in seen:
                    seen.add(item)
                    files.append(item)
    return files


def _promoted_reference_root(src: Path, home: Path) -> tuple[Path, Path] | None:
    """Promote a referenced wallpaper file to its complete wallpaper bundle.

    The returned tuple is ``(source_root, target_home_relative_root)``. System
    wallpapers are deliberately copied into the target user's local wallpaper
    directory so the visual result is independent of the target distribution.
    """
    roots = [
        (home / ".local/share/wallpapers", Path(".local/share/wallpapers")),
        (Path("/usr/local/share/wallpapers"), Path(".local/share/wallpapers")),
        (Path("/usr/share/wallpapers"), Path(".local/share/wallpapers")),
    ]
    for root, target_root in roots:
        try:
            rel = src.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        if len(rel.parts) >= 1:
            candidate = root / rel.parts[0]
            if candidate.is_dir():
                return candidate, target_root / rel.parts[0]
    return None


def _external_asset_target(src: Path) -> Path:
    digest = sha256_file(src)[:12]
    safe_name = src.name.replace("/", "_")
    return Path(".local/share/linux-iso/captured-assets") / f"{digest}-{safe_name}"


def _external_directory_target(src: Path) -> Path:
    digest = hashlib.sha256(str(src.resolve()).encode("utf-8")).hexdigest()[:12]
    safe_name = src.name.replace("/", "_") or "wallpaper"
    return Path(".local/share/linux-iso/captured-wallpapers") / f"{digest}-{safe_name}"


def _local_config_path_candidate(raw: str, home: Path) -> Path | None:
    """Decode a local config path even when the referenced file was moved.

    Plasma can retain stale wallpaper paths after a file is moved within the
    user's Pictures tree.  Strict-fidelity capture needs the decoded path so it
    can repair that reference instead of rejecting an otherwise complete
    profile.
    """
    raw = raw.strip().strip('"').strip("'")
    if not raw or raw.startswith(("http://", "https://")):
        return None
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        if parsed.scheme != "file":
            return None
        raw = unquote(parsed.path)
    else:
        raw = unquote(raw)
    if raw.startswith("$HOME/"):
        raw = str(home / raw[len("$HOME/") :])
    elif raw.startswith("~/"):
        raw = str(home / raw[2:])
    if not raw.startswith("/"):
        return None
    try:
        return Path(raw).expanduser().resolve(strict=False)
    except OSError:
        return None


def _normalize_local_config_path(raw: str, home: Path) -> Path | None:
    resolved = _local_config_path_candidate(raw, home)
    return resolved if resolved is not None and resolved.exists() else None


def _launcher_icon_name(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("Icon="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


def _named_launcher_icon_files(home: Path, icon_name: str) -> list[tuple[Path, Path]]:
    """Resolve named application icons commonly shipped in hicolor/pixmaps.

    Pinned launchers frequently use ``Icon=code`` rather than an absolute path.
    The source application may not be installed yet on the target, so copy the
    concrete icon bytes alongside the launcher to avoid generic placeholder icons.
    """
    if not icon_name or "/" in icon_name:
        return []
    stem = Path(icon_name).stem if Path(icon_name).suffix else icon_name
    extensions = {".png", ".svg", ".svgz", ".xpm"}
    result: list[tuple[Path, Path]] = []
    seen: set[Path] = set()

    hicolor_roots = [
        home / ".local/share/icons/hicolor",
        home / ".icons/hicolor",
        # Flatpak exports icons alongside exported .desktop files; capture them
        # so restored/pinned applications do not render generic placeholders.
        home / ".local/share/flatpak/exports/share/icons/hicolor",
        Path("/var/lib/flatpak/exports/share/icons/hicolor"),
        Path("/usr/local/share/icons/hicolor"),
        Path("/usr/share/icons/hicolor"),
    ]
    for root in hicolor_roots:
        if not root.is_dir():
            continue
        try:
            candidates = root.rglob(stem + ".*")
        except OSError:
            continue
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in extensions:
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                rel = candidate.relative_to(root)
            except ValueError:
                continue
            result.append((candidate, Path(".local/share/icons/hicolor") / rel))

    for root in (
        Path("/usr/local/share/pixmaps"),
        Path("/usr/share/pixmaps"),
        Path("/var/lib/snapd/desktop/icons"),
    ):
        if not root.is_dir():
            continue
        for ext in extensions:
            candidate = root / f"{stem}{ext}"
            if not candidate.is_file() or candidate.resolve() in seen:
                continue
            seen.add(candidate.resolve())
            target_dir = (
                Path(".local/share/icons/hicolor/scalable/apps")
                if ext in {".svg", ".svgz"}
                else Path(".local/share/icons/hicolor/256x256/apps")
            )
            result.append((candidate, target_dir / candidate.name))
    return result


def _wallpaper_config_references(home: Path) -> list[Path]:
    """Return local wallpaper files/directories named by Plasma config.

    Plasma can store either a concrete ``Image=`` file or slideshow/package
    directories (notably ``SlidePaths=``).  The generic asset scanner only sees
    paths with image extensions, so directory references need explicit capture.
    """
    path = home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    found: list[Path] = []
    seen: set[Path] = set()
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() not in {"Image", "SlidePaths"}:
            continue
        # KDE config lists may use commas or semicolons; Image itself is scalar.
        raw_values = [value] if key.strip() == "Image" else value.replace(";", ",").split(",")
        for raw in raw_values:
            resolved = _normalize_local_config_path(raw, home)
            if resolved is None or resolved in seen:
                continue
            seen.add(resolved)
            found.append(resolved)
    return found


def _relocated_wallpaper_references(home: Path) -> list[tuple[Path, Path]]:
    """Resolve stale home-local wallpaper paths by unique basename.

    KDE/Plasma may keep an old Image= path after a wallpaper is moved into a
    subdirectory.  If the original path is missing but exactly one file with the
    same basename exists below the old parent directory, treat that as a move and
    rewrite the captured config to the new portable location.  Ambiguous matches
    are deliberately left unresolved so verification still fails rather than
    guessing.
    """
    config = home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not config.is_file():
        return []
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    home_resolved = home.resolve()
    moved: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {"Image", "SlidePaths"}:
            continue
        raw_values = [value] if key == "Image" else value.replace(";", ",").split(",")
        for raw in raw_values:
            missing = _local_config_path_candidate(raw, home)
            if missing is None or missing.exists() or missing in seen:
                continue
            seen.add(missing)
            try:
                missing.relative_to(home_resolved)
            except ValueError:
                continue
            search_root = missing.parent if missing.parent.is_dir() else home_resolved
            try:
                matches = sorted(
                    {
                        item.resolve()
                        for item in search_root.rglob(missing.name)
                        if item.is_file() and not item.is_symlink() and not path_is_sensitive(item)
                    },
                    key=lambda item: str(item),
                )
            except OSError:
                continue
            if len(matches) == 1:
                moved.append((missing, matches[0]))
    return moved


def _payload_path_for_destination(payload_home: Path, destination: str) -> Path | None:
    prefix = "{{HOME}}/"
    if destination == "{{HOME}}":
        return payload_home
    if not destination.startswith(prefix):
        return None
    return payload_home / destination[len(prefix):]


def _rewrite_captured_references(
    items: list[CapturedFile],
    payload_home: Path,
    replacements: dict[str, str],
) -> None:
    if not replacements:
        return
    ordered = sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True)
    for item in items:
        path = _payload_path_for_destination(payload_home, item.destination)
        if path is None or not path.is_file():
            continue
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue
        updated = text
        rewrites = 0
        for old, new in ordered:
            encoded_old = quote(old, safe="/")
            encoded_new = quote(new, safe="/{}")
            variants = (
                (f"file://{old}", f"file://{new}"),
                (f"file://{encoded_old}", f"file://{encoded_new}"),
                (old, new),
                (encoded_old, encoded_new),
            )
            for old_token, new_token in variants:
                count = updated.count(old_token)
                if count:
                    updated = updated.replace(old_token, new_token)
                    rewrites += count
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            item.sha256 = sha256_file(path)
            item.rewritten_home_paths += rewrites


def _expanded_active_components(home: Path) -> list[dict[str, object]]:
    components: list[dict[str, object]] = [dict(item) for item in active_kde_components(home)]
    components.extend(dict(item) for item in active_kwin_user_components(home))
    seen = {(str(item["kind"]), str(item["name"])) for item in components}
    active_icons = [item for item in components if item.get("kind") == "icon-theme"]
    for item in active_icons:
        for inherited in icon_theme_inheritance_chain(home, str(item["name"])):
            token = ("icon-theme", inherited)
            if token in seen:
                continue
            seen.add(token)
            components.append(
                {
                    "kind": "icon-theme",
                    "name": inherited,
                    "inherited": True,
                    "inherited_from": item["name"],
                }
            )
    return components


def capture_profile(
    output: Path,
    home: Path | None = None,
    asset_mode: str = "active",
) -> Manifest:
    home = (home or Path.home()).expanduser().resolve()
    output = output.expanduser().resolve()
    if asset_mode not in {"active", "all"}:
        raise CaptureError("asset_mode must be 'active' or 'all'.")
    if output == home or output in home.parents:
        raise CaptureError("Output directory must not be the home directory or an ancestor of it.")

    desktop_name, desktop_version = detect_desktop()
    if desktop_name != "kde-plasma":
        raise CaptureError(f"v{__version__} currently supports KDE Plasma; detected: {desktop_name}")

    if output.exists():
        shutil.rmtree(output)
    payload_home = output / "payload/home"
    payload_home.mkdir(parents=True, exist_ok=True)

    configs, data_paths, terminal_paths = existing_kde_paths(home)
    slideshow_overrides = _slideshow_initial_overrides(home)
    runtime_wallpaper_states = _runtime_plasma_wallpaper_state(home)
    excluded: list[str] = []
    captured_configs: list[CapturedFile] = []
    captured_assets: list[CapturedFile] = []

    # Capture native Plasma/KDE and terminal state first.
    for src in configs + terminal_paths:
        if path_is_sensitive(src):
            excluded.append(str(src).replace(str(home), "{{HOME}}", 1))
            continue
        if src.is_dir():
            captured_configs.extend(_copy_tree(src, payload_home, home, "config", excluded))
        elif src.is_file():
            relative = _safe_relative(src, home)
            captured_configs.append(_copy_file(src, payload_home / relative, home, "config"))

    # Kickoff favorite membership is stored in KActivities' SQLite database,
    # not in the panel config. Capture only favorite rows plus the ordering
    # sections so the launcher is visually reproduced without importing usage
    # history or unrelated activity statistics.
    captured_configs.extend(_capture_kickoff_favorites_state(home, payload_home))

    widgets = referenced_widgets(home)
    local_plasmoids = user_plasmoids(home)
    active_components = _expanded_active_components(home)

    # Active-only capture is the default. Full mode is retained for diagnostics
    # and backwards-compatible "capture everything installed" behaviour.
    reference_roots: list[Path] = list(configs + terminal_paths)
    if asset_mode == "all":
        for src in data_paths:
            captured_assets.extend(_copy_tree(src, payload_home, home, "desktop-asset", excluded))
        reference_roots.extend(data_paths)
    else:
        always_roots = _active_only_always_roots(home)
        for src in always_roots:
            captured_assets.extend(_copy_tree(src, payload_home, home, "desktop-asset", excluded))
        reference_roots.extend(always_roots)

        # The list of installed KDE Store/manual themes is itself visible state
        # (System Settings -> Colors & Themes). Preserve user/manual packages,
        # while leaving distro-owned defaults to the native Pardus base.
        for kind, src, target_relative in _appearance_library_entries(home, active_components):
            captured_assets.extend(
                _copy_component(src, payload_home, target_relative, home, excluded, kind)
            )
            reference_roots.append(src)

    # Capture the visible XDG desktop surface (Desktop/Masaüstü/etc.) without
    # embedding arbitrary personal documents.  Application/link launchers are
    # part of the user-visible desktop and must survive cross-distro restore.
    desktop_surface_dir = _xdg_desktop_directory(home)
    desktop_surface_items: list[str] = []
    for launcher in _visible_desktop_launchers(home):
        captured = _copy_visible_desktop_launcher(launcher, payload_home, home)
        if captured is None:
            continue
        captured_assets.append(captured)
        desktop_surface_items.append(captured.destination)
        reference_roots.append(launcher)
        icon_name = _launcher_icon_name(launcher)
        if icon_name:
            for icon_src, target_relative in _named_launcher_icon_files(home, icon_name):
                icon_dst = payload_home / target_relative
                if not icon_dst.exists():
                    captured_assets.append(
                        _copy_file(icon_src, icon_dst, home, "desktop-surface-icon")
                    )

    desktop_applet_launchers: list[str] = []
    desktop_reference_replacements: dict[str, str] = {}
    for launcher in _plasma_desktop_launcher_references(home):
        try:
            relative = launcher.resolve().relative_to(home.resolve())
            target_relative = relative
        except ValueError:
            target_relative = Path(".local/share/applications") / launcher.name
        destination = payload_home / target_relative
        if not destination.exists():
            captured_assets.append(
                _copy_file(launcher, destination, home, "desktop-applet-launcher")
            )
        portable = f"{{{{HOME}}}}/{target_relative.as_posix()}"
        desktop_applet_launchers.append(portable)
        try:
            source_resolved = str(launcher.resolve())
        except OSError:
            source_resolved = str(launcher)
        desktop_reference_replacements[source_resolved] = portable
        reference_roots.append(launcher)
        icon_name = _launcher_icon_name(launcher)
        if icon_name:
            for icon_src, icon_target_relative in _named_launcher_icon_files(home, icon_name):
                icon_dst = payload_home / icon_target_relative
                if not icon_dst.exists():
                    captured_assets.append(
                        _copy_file(icon_src, icon_dst, home, "desktop-applet-icon")
                    )

    # Preserve pinned panel/task-manager launchers themselves.  Without the
    # corresponding .desktop files Plasma renders generic document icons even
    # when the panel layout was restored correctly.
    for launcher in referenced_application_desktops(home):
        try:
            relative = launcher.resolve().relative_to(home.resolve())
        except ValueError:
            destination = payload_home / ".local/share/applications" / launcher.name
            if not destination.exists():
                captured_assets.append(
                    _copy_file(launcher, destination, home, "panel-launcher")
                )
        else:
            destination = payload_home / relative
            if not destination.exists():
                captured_assets.append(_copy_file(launcher, destination, home, "panel-launcher"))
        reference_roots.append(launcher)

        icon_name = _launcher_icon_name(launcher)
        if icon_name:
            for icon_src, target_relative in _named_launcher_icon_files(home, icon_name):
                icon_dst = payload_home / target_relative
                if not icon_dst.exists():
                    captured_assets.append(
                        _copy_file(icon_src, icon_dst, home, "panel-launcher-icon")
                    )

    packages = collect_packages()
    package_index = {(p.provider, p.name): p for p in packages}
    widget_details: list[dict[str, object]] = []

    for plugin_id in widgets:
        if plugin_id in local_plasmoids:
            local_path = home / ".local/share/plasma/plasmoids" / plugin_id
            if asset_mode == "active":
                captured_assets.extend(
                    _copy_local_entry(local_path, payload_home, home, "plasmoid", excluded)
                )
            reference_roots.append(local_path)
            runtime = plasmoid_runtime_details(local_path)
            widget_details.append(
                {
                    "id": plugin_id,
                    "source": "user-local",
                    "bundled": True,
                    "bundle_root": _portable_home_path(local_path, home),
                    **runtime,
                }
            )
            continue
        system_path = system_plasmoid(plugin_id)
        if system_path is None:
            widget_details.append({"id": plugin_id, "source": "not-found", "bundled": False})
            continue
        metadata = system_path / "metadata.json"
        owner = package_owner(metadata if metadata.exists() else system_path)
        if owner:
            provider, package_name = owner
            reason = f"Provides referenced Plasma widget: {plugin_id}"
            _mark_required_package(packages, package_index, provider, package_name, reason)
            widget_details.append(
                {
                    "id": plugin_id,
                    "source": "system-package",
                    "provider": provider,
                    "package": package_name,
                    "bundled": False,
                }
            )
        else:
            destination_root = payload_home / ".local/share/plasma/plasmoids" / plugin_id
            captured_assets.extend(
                _copy_external_tree(system_path, destination_root, home, "system-plasmoid", excluded)
            )
            widget_details.append(
                {
                    "id": plugin_id,
                    "source": "system-unpackaged",
                    "bundled": True,
                    "bundle_root": f"{{{{HOME}}}}/.local/share/plasma/plasmoids/{plugin_id}",
                }
            )

    component_details: list[dict[str, object]] = []
    for component in active_components:
        kind = str(component["kind"])
        name = str(component["name"])
        inherited = bool(component.get("inherited"))
        user_paths, system_paths = component_locations(home, kind, name)
        local = next((path for path in user_paths if path.exists()), None)
        if local is not None:
            if asset_mode == "active":
                try:
                    local_target = local.relative_to(home)
                except ValueError:
                    local_target = Path(".local/share/linux-iso/appearance") / local.name
                captured_assets.extend(
                    _copy_component(
                        local,
                        payload_home,
                        local_target,
                        home,
                        excluded,
                        kind,
                    )
                )
            reference_roots.append(local)
            detail: dict[str, object] = {
                "kind": kind,
                "name": name,
                "source": "user-local",
                "bundled": True,
                "bundle_root": _portable_home_path(local, home),
            }
            if inherited:
                detail["inherited"] = True
                detail["inherited_from"] = component.get("inherited_from")
            if component.get("config_id"):
                detail["config_id"] = component.get("config_id")
            component_details.append(detail)
            continue

        system_entry = next((item for item in system_paths if item[0].exists()), None)
        if system_entry is None:
            if kind == "look-and-feel":
                detail = {
                    "kind": kind,
                    "name": name,
                    "source": "missing-meta-package",
                    "bundled": False,
                    "note": "global theme package is absent; active subcomponents are captured separately",
                }
            elif kind == "icon-theme" and inherited:
                # Freedesktop icon themes can name compatibility/fallback themes
                # which are not installed as a standalone directory on newer
                # desktops. The source machine already renders successfully, so
                # an unresolved inherited fallback is informative rather than
                # fatal. Keep it in the manifest so verification/audit can report
                # the portability caveat without rejecting the profile.
                detail = {
                    "kind": kind,
                    "name": name,
                    "source": "missing-inherited-fallback",
                    "bundled": False,
                    "note": "declared by icon-theme inheritance but not installed as a standalone theme",
                }
            else:
                detail = {"kind": kind, "name": name, "source": "not-found", "bundled": False}
            if inherited:
                detail["inherited"] = True
                detail["inherited_from"] = component.get("inherited_from")
            component_details.append(detail)
            continue

        system_path, target_relative = system_entry
        owner = package_owner(ownership_probe(system_path))
        if owner:
            provider, package_name = owner
            reason = f"Provides active KDE {kind}: {name}"
            _mark_required_package(packages, package_index, provider, package_name, reason)
            # Do not rely on the target distro shipping byte-identical theme assets.
            # Bundle the exact active component into the user's local data path as
            # well; user-local KDE assets override distro defaults while the package
            # remains required for any runtime dependencies it may provide.
            captured_assets.extend(
                _copy_component(system_path, payload_home, target_relative, home, excluded, kind)
            )
            detail = {
                "kind": kind,
                "name": name,
                "source": "system-package",
                "provider": provider,
                "package": package_name,
                "bundled": True,
                "bundle_root": f"{{{{HOME}}}}/{target_relative.as_posix()}",
            }
            if inherited:
                detail["inherited"] = True
                detail["inherited_from"] = component.get("inherited_from")
            component_details.append(detail)
        else:
            captured_assets.extend(
                _copy_component(system_path, payload_home, target_relative, home, excluded, kind)
            )
            detail = {
                "kind": kind,
                "name": name,
                "source": "system-unpackaged",
                "bundled": True,
                "bundle_root": f"{{{{HOME}}}}/{target_relative.as_posix()}",
            }
            if inherited:
                detail["inherited"] = True
                detail["inherited_from"] = component.get("inherited_from")
            component_details.append(detail)

    # Catch one-off icon/wallpaper/font paths referenced by active configs,
    # active appearance packages, launchers and terminal configuration. Capture
    # external/system paths too, then rewrite their references to portable user-
    # local destinations so Pardus assets cannot silently fall back to Kubuntu.
    referenced = set(
        find_referenced_assets(
            _reference_files(reference_roots), home, include_external=True
        )
    )
    referenced.update(_wallpaper_config_references(home))
    referenced.update(_runtime_wallpaper_files(home, runtime_wallpaper_states))
    relocated_wallpapers = _relocated_wallpaper_references(home)
    referenced.update(found for _missing, found in relocated_wallpapers)
    promoted_roots: set[Path] = set()
    copied_directories: set[Path] = set()
    home_resolved = home.resolve()
    replacements: dict[str, str] = dict(desktop_reference_replacements)
    for missing, found in relocated_wallpapers:
        target = f"{{{{HOME}}}}/{found.relative_to(home_resolved).as_posix()}"
        replacements[str(missing)] = target
        try:
            missing_relative = missing.relative_to(home_resolved)
        except ValueError:
            continue
        replacements[f"{{{{HOME}}}}/{missing_relative.as_posix()}"] = target
    for src in sorted(referenced, key=lambda item: str(item)):
        if path_is_sensitive(src):
            continue
        promoted = _promoted_reference_root(src, home)
        if promoted is not None:
            promoted_src, target_relative = promoted
            if promoted_src not in promoted_roots:
                promoted_roots.add(promoted_src)
                captured_assets.extend(
                    _copy_external_tree(
                        promoted_src,
                        payload_home / target_relative,
                        home,
                        "referenced-bundle",
                        excluded,
                    )
                )
            try:
                promoted_src.resolve().relative_to(home_resolved)
            except ValueError:
                replacements[str(promoted_src.resolve())] = (
                    f"{{{{HOME}}}}/{target_relative.as_posix()}"
                )
            continue

        if src.is_dir():
            try:
                relative = src.resolve().relative_to(home_resolved)
                target_relative = relative
            except ValueError:
                target_relative = _external_directory_target(src)
            if src.resolve() not in copied_directories:
                copied_directories.add(src.resolve())
                captured_assets.extend(
                    _copy_external_tree(
                        src,
                        payload_home / target_relative,
                        home,
                        "referenced-wallpaper-directory",
                        excluded,
                    )
                )
            replacements[str(src.resolve())] = f"{{{{HOME}}}}/{target_relative.as_posix()}"
            continue

        try:
            relative = src.resolve().relative_to(home_resolved)
        except ValueError:
            target_relative = _external_asset_target(src)
            destination = payload_home / target_relative
            if not destination.exists():
                captured_assets.append(
                    _copy_file(src, destination, home, "referenced-external-asset")
                )
            replacements[str(src.resolve())] = f"{{{{HOME}}}}/{target_relative.as_posix()}"
        else:
            destination = payload_home / relative
            if not destination.exists():
                captured_assets.append(_copy_file(src, destination, home, "referenced-asset"))

    captured_configs = _dedupe_captured(captured_configs)
    captured_assets = _dedupe_captured(captured_assets)
    _rewrite_captured_references(
        captured_configs + captured_assets, payload_home, replacements
    )
    _apply_slideshow_initial_overrides(payload_home, slideshow_overrides, captured_configs)
    _apply_runtime_wallpaper_state(
        payload_home, home, runtime_wallpaper_states, replacements, captured_configs
    )
    runtime_visible_wallpaper = _runtime_primary_visible_wallpaper(
        home, runtime_wallpaper_states, replacements
    )
    packages.sort(key=lambda p: (p.category, p.provider, p.name.lower()))
    desktop = DesktopProfile(
        desktop=desktop_name,
        version=desktop_version,
        configs=captured_configs,
        custom_assets=captured_assets,
        widgets=widgets,
        user_plasmoids=local_plasmoids,
        widget_details=widget_details,
        component_details=component_details,
    )
    security = {
        "safe_mode": True,
        "excluded_count": len(excluded),
        "excluded": excluded,
        "notes": [
            "Known key/credential stores are not captured.",
            "Possible secrets in shell startup files are redacted.",
            f"Files larger than 64 MiB are excluded from profile payload in v{__version__}.",
        ],
    }

    system_visual = _capture_system_visual_fidelity(output, home, component_details)
    source_info = _capture_source_branding(output, collect_system_info())
    visible_wallpaper = runtime_visible_wallpaper or _captured_visible_wallpaper(payload_home)
    slideshow_state = _captured_slideshow_state(payload_home, runtime_wallpaper_states)

    manifest = Manifest(
        schema_version=1,
        created_at=datetime.now(timezone.utc).isoformat(),
        source=source_info,
        desktop=desktop,
        packages=packages,
        security=security,
        restore={
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "application_install_mode": "online-selective",
            "profile_version": __version__,
            "asset_mode": asset_mode,
            "fidelity_schema": 12,
            "visible_wallpaper": visible_wallpaper,
            "slideshow": slideshow_state,
            "system_visual": system_visual,
            "desktop_surface": {
                "directory": _portable_home_path(desktop_surface_dir, home),
                "launchers": sorted(desktop_surface_items),
                "launcher_count": len(desktop_surface_items),
                "applet_launchers": sorted(set(desktop_applet_launchers)),
            },
        },
    )

    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.yaml").write_text(
        yaml.safe_dump(manifest.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps(
            {
                "desktop": desktop_name,
                "asset_mode": asset_mode,
                "config_files": len(captured_configs),
                "asset_files": len(captured_assets),
                "widgets": desktop.widgets,
                "user_plasmoids": desktop.user_plasmoids,
                "appearance_components": desktop.component_details,
                "packages": len(packages),
                "excluded": len(excluded),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest
