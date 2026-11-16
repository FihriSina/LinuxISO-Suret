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


def capture_profile(output: Path, home: Path | None = None) -> Manifest:
    home = (home or Path.home()).expanduser().resolve()
    output = output.expanduser().resolve()
    if output == home or output in home.parents:
        raise CaptureError("Output directory must not be the home directory or an ancestor of it.")

    desktop_name, desktop_version = detect_desktop()
    if desktop_name != "kde-plasma":
        raise CaptureError(f"v0.2.3 currently supports KDE Plasma; detected: {desktop_name}")

    if output.exists():
        shutil.rmtree(output)
    payload_home = output / "payload/home"
    payload_home.mkdir(parents=True, exist_ok=True)

    configs, data_paths, terminal_paths = existing_kde_paths(home)
    excluded: list[str] = []
    captured_configs: list[CapturedFile] = []
    captured_assets: list[CapturedFile] = []

    # Capture native Plasma/KDE configs first.
    for src in configs + terminal_paths:
        if path_is_sensitive(src):
            excluded.append(str(src).replace(str(home), "{{HOME}}", 1))
            continue
        if src.is_dir():
            captured_configs.extend(_copy_tree(src, payload_home, home, "config", excluded))
        elif src.is_file():
            relative = _safe_relative(src, home)
            captured_configs.append(_copy_file(src, payload_home / relative, home, "config"))

    # Capture user-local Plasma packages, icon themes, fonts, wallpapers, .desktop overrides, etc.
    for src in data_paths:
        captured_assets.extend(_copy_tree(src, payload_home, home, "desktop-asset", excluded))

    # Catch one-off icon/wallpaper/font paths referenced by Plasma, launchers,
    # plasmoid metadata/configuration and terminal configuration.
    reference_files: list[Path] = []
    for root in configs + terminal_paths + data_paths:
        if root.is_file():
            reference_files.append(root)
            continue
        if not root.is_dir():
            continue
        for item in root.rglob("*"):
            if not item.is_file() or item.is_symlink() or path_is_sensitive(item):
                continue
            if item.suffix.lower() in TEXT_EXTENSIONS or item.name.endswith("rc"):
                reference_files.append(item)

    referenced = find_referenced_assets(reference_files, home)
    for src in referenced:
        if path_is_sensitive(src):
            continue
        relative = _safe_relative(src, home)
        destination = payload_home / relative
        if destination.exists():
            continue
        captured_assets.append(_copy_file(src, destination, home, "referenced-asset"))

    widgets = referenced_widgets(home)
    local_plasmoids = user_plasmoids(home)
    packages = collect_packages()
    package_index = {(p.provider, p.name): p for p in packages}
    widget_details: list[dict[str, object]] = []

    for plugin_id in widgets:
        if plugin_id in local_plasmoids:
            widget_details.append({"id": plugin_id, "source": "user-local", "bundled": True})
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
                {"id": plugin_id, "source": "system-unpackaged", "bundled": True}
            )

    component_details: list[dict[str, object]] = []
    for component in active_kde_components(home):
        kind = component["kind"]
        name = component["name"]
        user_paths, system_paths = component_locations(home, kind, name)
        local = next((path for path in user_paths if path.exists()), None)
        if local is not None:
            component_details.append(
                {"kind": kind, "name": name, "source": "user-local", "bundled": True}
            )
            continue

        system_entry = next((item for item in system_paths if item[0].exists()), None)
        if system_entry is None:
            if kind == "look-and-feel":
                component_details.append(
                    {
                        "kind": kind,
                        "name": name,
                        "source": "missing-meta-package",
                        "bundled": False,
                        "note": "global theme package is absent; active subcomponents are captured separately",
                    }
                )
            else:
                component_details.append(
                    {"kind": kind, "name": name, "source": "not-found", "bundled": False}
                )
            continue

        system_path, target_relative = system_entry
        owner = package_owner(ownership_probe(system_path))
        if owner:
            provider, package_name = owner
            reason = f"Provides active KDE {kind}: {name}"
            _mark_required_package(packages, package_index, provider, package_name, reason)
            component_details.append(
                {
                    "kind": kind,
                    "name": name,
                    "source": "system-package",
                    "provider": provider,
                    "package": package_name,
                    "bundled": False,
                }
            )
        else:
            captured_assets.extend(
                _copy_component(system_path, payload_home, target_relative, home, excluded)
            )
            component_details.append(
                {"kind": kind, "name": name, "source": "system-unpackaged", "bundled": True}
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
            "Files larger than 64 MiB are excluded from profile payload in v0.2.3.",
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
            "profile_version": "0.2.3",
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
