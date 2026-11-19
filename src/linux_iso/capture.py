from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
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
from linux_iso.security.sanitizer import path_is_sensitive, sanitize_shell_text
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
            if src.name in SHELL_FILES or src.suffix.lower() in SHELL_EXTENSIONS:
                result = sanitize_shell_text(text)
                text = result.text
                sanitized = result.redacted_lines
            text, rewritten = _rewrite_home(text, home)
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
    """Pin slideshow desktops to the source-visible image for deterministic first boot.

    Plasma's slideshow plugin can ignore a persisted ``Image=`` value when a
    fresh target session starts and immediately choose a target-distro wallpaper.
    For a reproducible visual snapshot, Suret converts the copied slideshow
    containment to the static image plugin while retaining all captured slide
    files in the profile. This changes only the restored copy, never the source.
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
            if section in overrides:
                replacement = section.replace(
                    "[Wallpaper][org.kde.slideshow][General]",
                    "[Wallpaper][org.kde.image][General]",
                )
                if replacement != line:
                    line = replacement
                    changed = True
            new_lines.append(line)
            continue

        if line.strip().lower() == "wallpaperplugin=org.kde.slideshow":
            new_lines.append("wallpaperplugin=org.kde.image")
            changed = True
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
) -> list[CapturedFile]:
    destination = payload_home / target_relative
    if src.is_dir():
        return _copy_external_tree(src, destination, home, "appearance-component", excluded)
    if src.is_file():
        return [_copy_file(src, destination, home, "appearance-component")]
    return []


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

    for root in (Path("/usr/local/share/pixmaps"), Path("/usr/share/pixmaps")):
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
                captured_assets.extend(
                    _copy_local_entry(local, payload_home, home, "appearance-component", excluded)
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
                _copy_component(system_path, payload_home, target_relative, home, excluded)
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
                _copy_component(system_path, payload_home, target_relative, home, excluded)
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
    relocated_wallpapers = _relocated_wallpaper_references(home)
    referenced.update(found for _missing, found in relocated_wallpapers)
    promoted_roots: set[Path] = set()
    copied_directories: set[Path] = set()
    home_resolved = home.resolve()
    replacements: dict[str, str] = {}
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

    source_info = _capture_source_branding(output, collect_system_info())

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
            "fidelity_schema": 6,
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
