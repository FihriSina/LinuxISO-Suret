from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from linux_iso.branding import PRODUCT_NAME

CATEGORY_ORDER = [
    "internet",
    "communication",
    "office",
    "multimedia",
    "development",
    "gaming",
    "system",
    "other",
]

APPLICATION_PRESENTATION: dict[str, tuple[str, str]] = {
    "firefox": ("Firefox", "Web browser with privacy and developer tools."),
    "org.mozilla.firefox": ("Firefox", "Web browser with privacy and developer tools."),
    "signal-desktop": ("Signal", "Private messaging for desktop."),
    "org.signal.Signal": ("Signal", "Private messaging for desktop."),
    "org.onlyoffice.desktopeditors": ("ONLYOFFICE", "Documents, spreadsheets and presentations."),
    "vlc": ("VLC", "Versatile video and audio player."),
    "org.videolan.VLC": ("VLC", "Versatile video and audio player."),
    "mpv": ("MPV", "Fast, lightweight media player."),
    "ffmpeg": ("FFmpeg", "Audio and video conversion toolkit."),
    "io.freetubeapp.FreeTube": ("FreeTube", "Privacy-focused desktop YouTube client."),
    "org.flameshot.Flameshot": ("Flameshot", "Powerful screenshot and annotation tool."),
    "org.kde.koko": ("Koko", "Simple image gallery for KDE."),
    "git": ("Git", "Distributed version control system."),
    "cmake": ("CMake", "Cross-platform build system generator."),
    "code": ("Visual Studio Code", "Code editor with extension support."),
    "podman": ("Podman", "Daemonless container engine."),
    "com.google.AndroidStudio": ("Android Studio", "Android development environment."),
    "fastfetch": ("Fastfetch", "Fast system information utility."),
    "io.github.kolunmi.Bazaar": ("Bazaar", "Graphical application browser."),
    "com.brave.Browser": ("Brave", "Privacy-focused Chromium web browser."),
    "one.ablaze.floorp": ("Floorp", "Customizable Firefox-based web browser."),
    "app.zen_browser.zen": ("Zen Browser", "Minimal, customizable web browser."),
    "steam": ("Steam", "PC game library and storefront."),
    "com.valvesoftware.Steam": ("Steam", "PC game library and storefront."),
}


def _presentation(name: str, reason: str | None) -> tuple[str, str]:
    if name in APPLICATION_PRESENTATION:
        return APPLICATION_PRESENTATION[name]
    short = name.rsplit(".", 1)[-1].replace("-", " ").replace("_", " ").strip()
    display = " ".join(part.upper() if len(part) <= 3 else part.title() for part in short.split()) or name
    description = (reason or "Optional application. Selected by default; uncheck to skip.").strip()
    return display, description


CATEGORY_LABELS = {
    "internet": "Internet",
    "communication": "Communication",
    "office": "Office",
    "multimedia": "Multimedia",
    "development": "Development",
    "gaming": "Gaming",
    "system": "System Tools",
    "other": "Other Applications",
}


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "other"


def package_item_id(provider: str, name: str) -> str:
    digest = hashlib.blake2s(f"{provider}:{name}".encode("utf-8"), digest_size=5).hexdigest()
    return f"{_safe_slug(provider)}-{_safe_slug(name)[:42]}-{digest}"


def load_manifest(profile: Path) -> dict[str, Any]:
    path = profile / "manifest.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def build_catalog(profile: Path) -> dict[str, Any]:
    manifest = load_manifest(profile)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    required: list[dict[str, Any]] = []

    for package in manifest.get("packages", []):
        display_name, description = _presentation(package["name"], package.get("reason"))
        item = {
            "id": package_item_id(package.get("provider", "unknown"), package["name"]),
            "name": package["name"],
            "display_name": display_name,
            "description": description,
            "provider": package.get("provider", "unknown"),
            "category": package.get("category", "other"),
            "required_for_appearance": bool(package.get("required_for_appearance", False)),
            "reason": package.get("reason"),
            "source": package.get("source"),
            "source_url": package.get("source_url"),
            "installer_visible": bool(package.get("installer_visible", True)),
            "visibility_reason": package.get("visibility_reason"),
            "install_options": list(package.get("install_options", [])),
        }
        if item["required_for_appearance"]:
            required.append(item)
        elif item["installer_visible"]:
            groups[item["category"]].append(item)

    categories: list[dict[str, Any]] = []
    known = list(CATEGORY_ORDER)
    known.extend(sorted(set(groups) - set(known)))
    for category in known:
        items = sorted(groups.get(category, []), key=lambda p: (p["provider"], p["name"].lower()))
        if items:
            categories.append(
                {
                    "id": category,
                    "label": CATEGORY_LABELS.get(category, category.replace("-", " ").title()),
                    "items": items,
                }
            )

    hidden_optional = sum(
        1
        for package in manifest.get("packages", [])
        if not package.get("required_for_appearance", False)
        and not package.get("installer_visible", True)
    )
    return {
        "schema_version": 1,
        "product": PRODUCT_NAME,
        "required_for_appearance": sorted(required, key=lambda p: (p["provider"], p["name"].lower())),
        "categories": categories,
        "hidden_native_packages": hidden_optional,
    }


def write_catalog(profile: Path, destination: Path) -> Path:
    catalog = build_catalog(profile)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination
