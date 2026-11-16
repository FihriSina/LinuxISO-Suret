from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

from mydistro.assets import find_referenced_assets, sha256_file
from mydistro.desktop.kde import existing_kde_paths, referenced_widgets, user_plasmoids
from mydistro.models import CapturedFile, DesktopProfile, Manifest
from mydistro.packages.inventory import collect_packages
from mydistro.security.sanitizer import path_is_sensitive, sanitize_shell_text
from mydistro.system import collect_system_info, detect_desktop


TEXT_EXTENSIONS = {
    "", ".conf", ".ini", ".rc", ".list", ".desktop", ".profile", ".toml", ".fish", ".zsh", ".bash",
}

SHELL_FILES = {".zshrc", ".bashrc", "config.fish"}


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


def _copy_file(src: Path, dst: Path, home: Path, kind: str) -> CapturedFile:
    dst.parent.mkdir(parents=True, exist_ok=True)
    rewritten = 0
    sanitized = 0

    should_treat_as_text = src.name in SHELL_FILES or src.suffix.lower() in TEXT_EXTENSIONS or src.name.endswith("rc")
    if should_treat_as_text and src.stat().st_size <= 8 * 1024 * 1024:
        try:
            text = src.read_text(encoding="utf-8", errors="strict")
            if src.name in SHELL_FILES:
                result = sanitize_shell_text(text)
                text = result.text
                sanitized = result.redacted_lines
            text, rewritten = _rewrite_home(text, home)
            dst.write_text(text, encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            shutil.copy2(src, dst)
    else:
        shutil.copy2(src, dst)

    return CapturedFile(
        source=str(src).replace(str(home), "{{HOME}}", 1),
        destination=str(dst),
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


def capture_profile(output: Path, home: Path | None = None) -> Manifest:
    home = (home or Path.home()).expanduser().resolve()
    output = output.expanduser().resolve()
    if output == home or output in home.parents:
        raise CaptureError("Output directory must not be the home directory or an ancestor of it.")

    desktop_name, desktop_version = detect_desktop()
    if desktop_name != "kde-plasma":
        raise CaptureError(f"v0.1 currently supports KDE Plasma; detected: {desktop_name}")

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

    # Catch custom one-off icon/wallpaper/font paths referenced directly by configs.
    referenced = find_referenced_assets(configs + terminal_paths, home)
    already = {Path(c.source).resolve() for c in captured_assets + captured_configs}
    for src in referenced:
        if src.resolve() in already or path_is_sensitive(src):
            continue
        relative = _safe_relative(src, home)
        captured_assets.append(_copy_file(src, payload_home / relative, home, "referenced-asset"))

    desktop = DesktopProfile(
        desktop=desktop_name,
        version=desktop_version,
        configs=captured_configs,
        custom_assets=captured_assets,
        widgets=referenced_widgets(home),
        user_plasmoids=user_plasmoids(home),
    )

    packages = collect_packages()
    security = {
        "safe_mode": True,
        "excluded_count": len(excluded),
        "excluded": excluded,
        "notes": [
            "Known key/credential stores are not captured.",
            "Possible secrets in shell startup files are redacted.",
            "Files larger than 64 MiB are excluded from profile payload in v0.1.",
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
            "profile_version": "0.1",
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
                "packages": len(packages),
                "excluded": len(excluded),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest
