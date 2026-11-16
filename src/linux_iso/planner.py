from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from linux_iso.branding import PRODUCT_NAME


def load_manifest(profile: Path) -> dict:
    return yaml.safe_load((profile / "manifest.yaml").read_text(encoding="utf-8"))


def _visible_optional(packages: list[dict]) -> list[dict]:
    return [
        p
        for p in packages
        if not p.get("required_for_appearance") and p.get("installer_visible", True)
    ]



def _asset_bundle(item: dict) -> tuple[str, str, str] | None:
    """Return (bundle_kind, bundle_name, portable_root) for known asset trees."""
    destination = str(item.get("destination") or "")
    prefix = "{{HOME}}/"
    if not destination.startswith(prefix):
        return None
    rel = destination[len(prefix):]
    parts = rel.split("/")

    grouped_roots = {
        (".local", "share", "plasma", "plasmoids"): "plasmoid",
        (".local", "share", "plasma", "desktoptheme"): "plasma-theme",
        (".local", "share", "plasma", "look-and-feel"): "look-and-feel",
        (".local", "share", "plasma", "layout-templates"): "plasma-layout",
        (".local", "share", "aurorae", "themes"): "window-decoration",
        (".local", "share", "wallpapers"): "wallpaper",
        (".local", "share", "themes"): "theme",
        (".themes",): "theme",
        (".local", "share", "icons"): "icon-theme",
        (".icons",): "icon-theme",
        (".local", "share", "kwin", "scripts"): "kwin-script",
        (".local", "share", "kwin", "effects"): "kwin-effect",
        (".local", "share", "kwin", "tabbox"): "kwin-tabbox",
        (".local", "share", "kwin", "decorations"): "kwin-decoration",
        (".local", "share", "konsole"): "konsole-profile",
    }

    for root_parts, kind in grouped_roots.items():
        if tuple(parts[: len(root_parts)]) != root_parts:
            continue
        if len(parts) <= len(root_parts):
            return None
        name = parts[len(root_parts)]
        root = "{{HOME}}/" + "/".join((*root_parts, name))
        return kind, name, root

    single_roots = {
        (".local", "share", "fonts"): ("font-collection", "user-fonts"),
        (".fonts",): ("font-collection", "user-fonts"),
        (".local", "share", "applications"): ("desktop-launchers", "user-launchers"),
        (".local", "share", "color-schemes"): ("color-schemes", "user-color-schemes"),
    }
    for root_parts, (kind, name) in single_roots.items():
        if tuple(parts[: len(root_parts)]) == root_parts:
            root = "{{HOME}}/" + "/".join(root_parts)
            return kind, name, root
    return None


def _group_assets(assets: list[dict]) -> tuple[list[dict], list[dict]]:
    bundles: dict[tuple[str, str, str], int] = {}
    standalone: list[dict] = []
    for item in assets:
        bundle = _asset_bundle(item)
        # One-off references outside managed desktop trees stay individually visible.
        if bundle is None or item.get("kind") == "referenced-asset":
            standalone.append(item)
            continue
        bundles[bundle] = bundles.get(bundle, 0) + 1

    grouped = [
        {"kind": kind, "name": name, "root": root, "files": count}
        for (kind, name, root), count in bundles.items()
    ]
    grouped.sort(key=lambda x: (x["kind"], x["name"].casefold()))
    standalone.sort(key=lambda x: str(x.get("destination", "")).casefold())
    return grouped, standalone

def summarize(profile: Path) -> str:
    manifest = load_manifest(profile)
    desktop = manifest["desktop"]
    packages = manifest.get("packages", [])
    visible = _visible_optional(packages)
    categories = Counter(p.get("category", "other") for p in visible)
    providers = Counter(p.get("provider", "unknown") for p in packages)
    required = [p for p in packages if p.get("required_for_appearance")]
    hidden = [
        p
        for p in packages
        if not p.get("required_for_appearance") and not p.get("installer_visible", True)
    ]

    lines = [
        f"Profile: {profile}",
        f"Source: {manifest['source'].get('distro_name')}",
        f"Desktop: {desktop.get('desktop')} {desktop.get('version') or ''}".rstrip(),
        f"Captured KDE config files: {len(desktop.get('configs', []))}",
        f"Captured assets: {len(desktop.get('custom_assets', []))}",
        f"Referenced widgets: {len(desktop.get('widgets', []))}",
        f"User-local plasmoids: {len(desktop.get('user_plasmoids', []))}",
        f"Resolved appearance components: {len(desktop.get('component_details', []))}",
        f"Selectable online applications: {len(visible)}",
        f"Appearance-required packages/components: {len(required)}",
        f"Native packages retained but hidden from chooser: {len(hidden)}",
        "Package providers: " + ", ".join(f"{k}={v}" for k, v in sorted(providers.items())),
        "Visible categories: " + ", ".join(f"{k}={v}" for k, v in sorted(categories.items())),
    ]
    return "\n".join(lines)


def audit(profile: Path) -> str:
    manifest = load_manifest(profile)
    desktop = manifest.get("desktop", {})
    packages = manifest.get("packages", [])
    security = manifest.get("security", {})

    asset_mode = manifest.get("restore", {}).get("asset_mode", "legacy/all")
    lines = [
        f"{PRODUCT_NAME} profile audit",
        "=" * 31,
        f"Asset capture mode: {asset_mode}",
        "",
        "Appearance asset bundles",
        "------------------------",
    ]
    assets = desktop.get("custom_assets", [])
    bundles, standalone = _group_assets(assets)
    if not bundles:
        lines.append("(none grouped)")
    for bundle in bundles:
        lines.append(
            f"- {bundle['kind']}={bundle['name']}: {bundle['files']} files "
            f"({bundle['root']})"
        )

    lines.extend(["", "Standalone / referenced assets", "----------------------------"])
    if not standalone:
        lines.append("(none captured)")
    for item in standalone:
        lines.append(
            f"- {item.get('kind', 'asset')}: {item.get('source')} -> {item.get('destination')}"
        )
    lines.append(
        f"Total: {len(assets)} asset files; {len(bundles)} grouped bundles; "
        f"{len(standalone)} standalone entries."
    )

    lines.extend(["", "Plasma widgets", "--------------"])
    details = desktop.get("widget_details", [])
    if not details:
        for widget in desktop.get("widgets", []):
            lines.append(f"- {widget}")
    for widget in details:
        suffix = []
        if widget.get("package"):
            suffix.append(f"package={widget.get('provider')}:{widget.get('package')}")
        suffix.append(f"bundled={'yes' if widget.get('bundled') else 'no'}")
        lines.append(f"- {widget.get('id')}: {widget.get('source')} ({', '.join(suffix)})")

    lines.extend(["", "Active KDE appearance components", "--------------------------------"])
    components = desktop.get("component_details", [])
    if not components:
        lines.append("(none resolved)")
    for component in components:
        suffix = []
        if component.get("package"):
            suffix.append(f"package={component.get('provider')}:{component.get('package')}")
        suffix.append(f"bundled={'yes' if component.get('bundled') else 'no'}")
        if component.get("inherited"):
            suffix.append(f"inherited-from={component.get('inherited_from')}")
        if component.get("note"):
            suffix.append(f"note={component.get('note')}")
        lines.append(
            f"- {component.get('kind')}={component.get('name')}: "
            f"{component.get('source')} ({', '.join(suffix)})"
        )

    lines.extend(["", "Appearance requirements", "-----------------------"])
    required = [p for p in packages if p.get("required_for_appearance")]
    if not required:
        lines.append("(none detected)")
    for package in required:
        reason = package.get("reason") or "appearance dependency"
        lines.append(f"- {package.get('provider')}:{package.get('name')} — {reason}")

    lines.extend(["", "Optional installer applications", "-------------------------------"])
    visible = _visible_optional(packages)
    if not visible:
        lines.append("(none detected)")
    grouped: dict[str, list[str]] = {}
    for package in visible:
        grouped.setdefault(package.get("category", "other"), []).append(
            f"{package.get('provider')}:{package.get('name')}"
        )
    for category in sorted(grouped):
        lines.append(f"- {category}: {', '.join(sorted(grouped[category], key=str.lower))}")

    hidden = [
        p
        for p in packages
        if not p.get("required_for_appearance") and not p.get("installer_visible", True)
    ]
    lines.extend(["", "Chooser filtering", "-----------------"])
    lines.append(f"Hidden native/manual packages: {len(hidden)}")
    if hidden:
        sample = ", ".join(p.get("name", "?") for p in hidden[:12])
        lines.append(f"Sample: {sample}" + (" …" if len(hidden) > 12 else ""))

    lines.extend(["", "Security", "--------"])
    lines.append(f"Safe mode: {'yes' if security.get('safe_mode') else 'unknown'}")
    lines.append(f"Excluded paths/files: {security.get('excluded_count', len(security.get('excluded', [])))}")
    for note in security.get("notes", []):
        lines.append(f"- {note}")

    return "\n".join(lines)
