from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import yaml


def load_manifest(profile: Path) -> dict:
    return yaml.safe_load((profile / "manifest.yaml").read_text(encoding="utf-8"))


def summarize(profile: Path) -> str:
    manifest = load_manifest(profile)
    desktop = manifest["desktop"]
    packages = manifest.get("packages", [])
    categories = Counter(p.get("category", "other") for p in packages)
    providers = Counter(p.get("provider", "unknown") for p in packages)
    required = [p for p in packages if p.get("required_for_appearance")]

    lines = [
        f"Profile: {profile}",
        f"Source: {manifest['source'].get('distro_name')}",
        f"Desktop: {desktop.get('desktop')} {desktop.get('version') or ''}".rstrip(),
        f"Captured KDE config files: {len(desktop.get('configs', []))}",
        f"Captured assets: {len(desktop.get('custom_assets', []))}",
        f"Referenced widgets: {len(desktop.get('widgets', []))}",
        f"User-local plasmoids: {len(desktop.get('user_plasmoids', []))}",
        f"Selectable online packages: {len(packages)}",
        f"Appearance-related packages: {len(required)}",
        "Package providers: " + ", ".join(f"{k}={v}" for k, v in sorted(providers.items())),
        "Categories: " + ", ".join(f"{k}={v}" for k, v in sorted(categories.items())),
    ]
    return "\n".join(lines)
