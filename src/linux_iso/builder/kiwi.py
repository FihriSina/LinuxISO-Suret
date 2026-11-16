from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from linux_iso.builder.calamares import generate_calamares_overlay


class BuilderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AptRepository:
    alias: str
    url: str
    distribution: str
    components: str


@dataclass(frozen=True)
class BaseRecipe:
    id: str
    image_name: str
    native_provider: str
    repositories: tuple[AptRepository, ...]
    bootstrap_packages: tuple[str, ...]
    image_packages: tuple[str, ...]


UBUNTU_2604_KDE = BaseRecipe(
    id="ubuntu-26.04-kde",
    image_name="linux-iso-naks-ubuntu-26.04",
    native_provider="apt",
    repositories=(
        AptRepository(
            "ubuntu",
            "https://archive.ubuntu.com/ubuntu",
            "resolute",
            "main restricted universe multiverse",
        ),
        AptRepository(
            "ubuntu-updates",
            "https://archive.ubuntu.com/ubuntu",
            "resolute-updates",
            "main restricted universe multiverse",
        ),
        AptRepository(
            "ubuntu-security",
            "https://security.ubuntu.com/ubuntu",
            "resolute-security",
            "main restricted universe multiverse",
        ),
    ),
    bootstrap_packages=(
        "base-files",
        "base-passwd",
        "bash",
        "coreutils",
        "dpkg",
        "apt",
        "libc6",
        "systemd-sysv",
    ),
    image_packages=(
        "ca-certificates",
        "linux-generic",
        "kubuntu-desktop",
        "calamares",
        "calamares-settings-kubuntu",
        "python3",
        "sudo",
        "network-manager",
    ),
)

RECIPES = {UBUNTU_2604_KDE.id: UBUNTU_2604_KDE}


PATCH_CALAMARES = r'''#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import yaml

SETTINGS = Path("/etc/calamares/settings.conf")
FRAGMENT = Path("/etc/calamares/linux-iso-settings-fragment.yaml")


def insert_unique(items, values, before=None, after=None):
    for value in values:
        if value in items:
            continue
        if before in items:
            items.insert(items.index(before), value)
        elif after in items:
            items.insert(items.index(after) + 1, value)
        else:
            items.append(value)


def main():
    if not SETTINGS.is_file() or not FRAGMENT.is_file():
        raise SystemExit("Calamares settings or Linux ISO fragment missing")
    settings = yaml.safe_load(SETTINGS.read_text(encoding="utf-8")) or {}
    fragment = yaml.safe_load(FRAGMENT.read_text(encoding="utf-8")) or {}

    modules_search = settings.setdefault("modules-search", ["local"])
    custom_modules = "/usr/share/linux-iso/calamares/modules"
    if custom_modules not in modules_search:
        modules_search.append(custom_modules)

    instances = settings.setdefault("instances", [])
    existing = {(x.get("module"), x.get("id")) for x in instances if isinstance(x, dict)}
    for item in fragment.get("instances", []):
        key = (item.get("module"), item.get("id"))
        if key not in existing:
            instances.append(item)
            existing.add(key)

    patch = fragment.get("sequence_patch", {})
    chooser = patch.get("insert_before_summary", [])
    jobs = patch.get("insert_in_exec_after_users", [])
    for phase in settings.get("sequence", []):
        if not isinstance(phase, dict):
            continue
        if "show" in phase and "summary" in phase["show"]:
            insert_unique(phase["show"], chooser, before="summary")
        if "exec" in phase and "users" in phase["exec"]:
            insert_unique(phase["exec"], jobs, after="users")

    SETTINGS.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
'''


def _read_manifest(profile: Path) -> dict[str, Any]:
    path = profile / "manifest.yaml"
    if not path.is_file():
        raise BuilderError(f"Missing profile manifest: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}



def _validate_recipe_compatibility(manifest: dict[str, Any], recipe: BaseRecipe) -> None:
    native_providers = {
        p.get("provider")
        for p in manifest.get("packages", [])
        if p.get("provider") in {"apt", "pacman", "dnf", "zypper"}
    }
    incompatible = sorted(p for p in native_providers if p != recipe.native_provider)
    if incompatible:
        raise BuilderError(
            f"Recipe {recipe.id} uses {recipe.native_provider}, but the profile contains "
            f"native packages from: {', '.join(incompatible)}. "
            "Cross-family package translation is not implemented yet."
        )


def _required_base_packages(manifest: dict[str, Any]) -> list[str]:
    return sorted(
        {
            p["name"]
            for p in manifest.get("packages", [])
            if p.get("provider") == "apt" and p.get("required_for_appearance")
        }
    )


def _optional_provider_support(manifest: dict[str, Any]) -> list[str]:
    providers = {p.get("provider") for p in manifest.get("packages", [])}
    packages: list[str] = []
    if "flatpak" in providers:
        packages.append("flatpak")
    if "snap" in providers:
        packages.append("snapd")
    return packages


def _indent_xml(root: ET.Element) -> None:
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        pass


def _write_config_xml(destination: Path, recipe: BaseRecipe, manifest: dict[str, Any]) -> None:
    root = ET.Element("image", {"schemaversion": "8.5", "name": recipe.image_name})
    description = ET.SubElement(root, "description", {"type": "system"})
    ET.SubElement(description, "author").text = "Linux ISO project"
    ET.SubElement(description, "contact").text = "local-build"
    ET.SubElement(description, "specification").text = "Linux ISO — Nakş personalized KDE Plasma live image"

    preferences = ET.SubElement(root, "preferences")
    ET.SubElement(preferences, "version").text = "0.2.3"
    ET.SubElement(preferences, "packagemanager").text = "apt"
    ET.SubElement(preferences, "locale").text = "en_US"
    ET.SubElement(preferences, "timezone").text = "UTC"
    ET.SubElement(
        preferences,
        "type",
        {
            "image": "iso",
            "primary": "true",
            "flags": "overlay",
            "filesystem": "squashfs",
            "bootloader": "grub2",
        },
    )

    for repo in recipe.repositories:
        node = ET.SubElement(
            root,
            "repository",
            {
                "type": "apt-deb",
                "alias": repo.alias,
                "imageinclude": "true",
                "components": repo.components,
                "distribution": repo.distribution,
            },
        )
        ET.SubElement(node, "source", {"path": repo.url})

    bootstrap = ET.SubElement(root, "packages", {"type": "bootstrap"})
    for name in recipe.bootstrap_packages:
        ET.SubElement(bootstrap, "package", {"name": name})

    image = ET.SubElement(root, "packages", {"type": "image"})
    packages = set(recipe.image_packages)
    packages.update(_required_base_packages(manifest))
    packages.update(_optional_provider_support(manifest))
    for name in sorted(packages):
        ET.SubElement(image, "package", {"name": name})

    _indent_xml(root)
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def _write_build_scripts(destination: Path) -> None:
    patcher = destination / "root/usr/lib/linux-iso/patch-calamares.py"
    patcher.parent.mkdir(parents=True, exist_ok=True)
    patcher.write_text(PATCH_CALAMARES, encoding="utf-8")
    patcher.chmod(0o755)

    config_sh = destination / "config.sh"
    config_sh.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        "test -f /.kconfig && . /.kconfig\n"
        "python3 /usr/lib/linux-iso/patch-calamares.py\n",
        encoding="utf-8",
    )
    config_sh.chmod(0o755)

    build_sh = destination / "build.sh"
    build_sh.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "OUT=${1:-./build-result}\n"
        "sudo kiwi-ng system build --description . --target-dir \"$OUT\"\n",
        encoding="utf-8",
    )
    build_sh.chmod(0o755)


def generate_kiwi_project(
    profile: Path,
    destination: Path,
    recipe_id: str = UBUNTU_2604_KDE.id,
) -> Path:
    profile = profile.expanduser().resolve()
    destination = destination.expanduser().resolve()
    manifest = _read_manifest(profile)
    if recipe_id not in RECIPES:
        raise BuilderError(f"Unknown KIWI recipe: {recipe_id}")
    recipe = RECIPES[recipe_id]
    _validate_recipe_compatibility(manifest, recipe)

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    overlay = destination / "root"
    share_profile = overlay / "usr/share/linux-iso/profile"
    share_profile.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(profile, share_profile)

    generate_calamares_overlay(profile, overlay)
    _write_build_scripts(destination)
    _write_config_xml(destination / "config.xml", recipe, manifest)

    required = _required_base_packages(manifest)
    marker = destination / "README-BUILDER.txt"
    marker.write_text(
        "Linux ISO — Nakş v0.2.3 KIWI project\n"
        f"Recipe: {recipe.id}\n"
        f"Appearance packages embedded in base image: {len(required)}\n"
        "Run ./build.sh on a KIWI NG build host.\n"
        "The generated recipe is experimental until boot/install validation in QEMU succeeds.\n",
        encoding="utf-8",
    )
    return destination


def generate_kiwi_overlay(profile: Path, destination: Path) -> Path:
    """Backward-compatible name; v0.2 now stages a full KIWI project."""
    return generate_kiwi_project(profile, destination)
