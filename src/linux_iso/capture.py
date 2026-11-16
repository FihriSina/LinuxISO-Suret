from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

from linux_iso.assets import find_referenced_assets, sha256_file
from linux_iso.desktop.kde import (
    active_kde_components,
    component_locations,
    existing_kde_paths,
    package_owner,
    ownership_probe,
    icon_theme_inheritance_chain,
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


class CaptureError(RuntimeError):
    pass


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
        home / ".local/share/kwin/scripts",
        home / ".local/share/kwin/effects",
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


def _promoted_reference_root(src: Path, home: Path) -> Path | None:
    """Promote referenced wallpaper package files to the whole wallpaper bundle."""
    root = home / ".local/share/wallpapers"
    try:
        rel = src.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if len(rel.parts) >= 2:
        candidate = root / rel.parts[0]
        if candidate.is_dir():
            return candidate
    return None


def _expanded_active_components(home: Path) -> list[dict[str, object]]:
    components: list[dict[str, object]] = [dict(item) for item in active_kde_components(home)]
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
        raise CaptureError(f"v0.2.7 currently supports KDE Plasma; detected: {desktop_name}")

    if output.exists():
        shutil.rmtree(output)
    payload_home = output / "payload/home"
    payload_home.mkdir(parents=True, exist_ok=True)

    configs, data_paths, terminal_paths = existing_kde_paths(home)
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

    widgets = referenced_widgets(home)
    local_plasmoids = user_plasmoids(home)
    active_components = _expanded_active_components(home)

    # v0.2.7 defaults to active-only capture. Full mode is retained for diagnostics
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
            widget_details.append(
                {
                    "id": plugin_id,
                    "source": "user-local",
                    "bundled": True,
                    "bundle_root": _portable_home_path(local_path, home),
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
            detail = {
                "kind": kind,
                "name": name,
                "source": "system-package",
                "provider": provider,
                "package": package_name,
                "bundled": False,
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
    # active appearance packages, launchers and terminal configuration.
    referenced = find_referenced_assets(_reference_files(reference_roots), home)
    promoted_roots: set[Path] = set()
    for src in referenced:
        if path_is_sensitive(src):
            continue
        promoted = _promoted_reference_root(src, home)
        if promoted is not None and promoted not in promoted_roots:
            promoted_roots.add(promoted)
            captured_assets.extend(
                _copy_tree(promoted, payload_home, home, "referenced-bundle", excluded)
            )
            continue
        relative = _safe_relative(src, home)
        destination = payload_home / relative
        if destination.exists():
            continue
        captured_assets.append(_copy_file(src, destination, home, "referenced-asset"))

    captured_configs = _dedupe_captured(captured_configs)
    captured_assets = _dedupe_captured(captured_assets)
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
            "Files larger than 64 MiB are excluded from profile payload in v0.2.7.",
        ],
    }

    manifest = Manifest(
        schema_version=1,
        created_at=datetime.now(timezone.utc).isoformat(),
        source=collect_system_info(),
        desktop=desktop,
        packages=packages,
        security=security,
        restore={
            "home_placeholder": "{{HOME}}",
            "payload_root": "payload/home",
            "application_install_mode": "online-selective",
            "profile_version": "0.2.5",
            "asset_mode": asset_mode,
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
