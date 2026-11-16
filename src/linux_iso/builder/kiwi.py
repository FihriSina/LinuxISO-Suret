from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from linux_iso import __version__
from linux_iso.branding import PRODUCT_NAME
from linux_iso.verification import verify_profile
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
    target_plasma_version: str | None = None
    preferred_box: str = "ubuntu"


UBUNTU_2604_KDE = BaseRecipe(
    id="ubuntu-26.04-kde",
    image_name="linux-iso-suret-ubuntu-26.04",
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
        "sddm",
    ),
    target_plasma_version="6.6",
    preferred_box="ubuntu",
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


LIVE_PROFILE_SCRIPT = r'''#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
from pathlib import Path

PAYLOAD = Path("/usr/share/linux-iso/profile/payload/home")
TARGET = Path("/home/live")


def ids():
    for line in Path("/etc/passwd").read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split(":")
        if len(fields) >= 4 and fields[0] == "live":
            return int(fields[2]), int(fields[3])
    raise RuntimeError("live user is missing")


def main():
    if not PAYLOAD.is_dir():
        raise SystemExit("Linux ISO profile payload is missing")
    TARGET.mkdir(parents=True, exist_ok=True)
    uid, gid = ids()
    for src in PAYLOAD.rglob("*"):
        rel = src.relative_to(PAYLOAD)
        dst = TARGET / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            os.chown(dst, uid, gid)
            continue
        if not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = src.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            shutil.copy2(src, dst)
        else:
            dst.write_text(text.replace("{{HOME}}", "/home/live"), encoding="utf-8")
            shutil.copymode(src, dst)
        os.chown(dst, uid, gid)
    os.chown(TARGET, uid, gid)


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
    ET.SubElement(description, "specification").text = f"{PRODUCT_NAME} personalized KDE Plasma live image"

    preferences = ET.SubElement(root, "preferences")
    ET.SubElement(preferences, "version").text = __version__
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

    users = ET.SubElement(root, "users")
    ET.SubElement(
        users,
        "user",
        {
            "name": "live",
            "password": "live",
            "pwdformat": "plain",
            "home": "/home/live",
            "groups": "users,sudo,audio,video,plugdev,netdev",
            "realname": "Linux ISO - Suret Live",
            "shell": "/bin/bash",
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


def _write_build_scripts(destination: Path, recipe: BaseRecipe) -> None:
    patcher = destination / "root/usr/lib/linux-iso/patch-calamares.py"
    patcher.parent.mkdir(parents=True, exist_ok=True)
    patcher.write_text(PATCH_CALAMARES, encoding="utf-8")
    patcher.chmod(0o755)

    live_profile = destination / "root/usr/lib/linux-iso/apply-live-profile.py"
    live_profile.write_text(LIVE_PROFILE_SCRIPT, encoding="utf-8")
    live_profile.chmod(0o755)

    installer = destination / "root/usr/bin/linux-iso-installer"
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "if command -v calamares-launch-normal >/dev/null 2>&1; then\n"
        "  exec sudo -E calamares-launch-normal\n"
        "fi\n"
        "exec sudo -E calamares\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)

    config_sh = destination / "config.sh"
    config_sh.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        "test -f /.kconfig && . /.kconfig\n"
        "python3 /usr/lib/linux-iso/patch-calamares.py\n"
        "python3 /usr/lib/linux-iso/apply-live-profile.py\n"
        "install -d -m 0755 /etc/sddm.conf.d\n"
        "cat > /etc/sddm.conf.d/99-linux-iso-live.conf <<'EOF'\n"
        "[Autologin]\n"
        "User=live\n"
        "Session=plasma\n"
        "Relogin=true\n"
        "EOF\n"
        "install -d -m 0755 /etc/sudoers.d\n"
        "echo 'live ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/99-linux-iso-live\n"
        "chmod 0440 /etc/sudoers.d/99-linux-iso-live\n"
        "install -d -o live -g users -m 0755 /home/live/Desktop\n"
        "cat > /home/live/Desktop/linux-iso-installer.desktop <<'EOF'\n"
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Install Linux ISO - Suret\n"
        "Comment=Install this personalized Linux system\n"
        "Exec=linux-iso-installer\n"
        "Icon=system-software-install\n"
        "Terminal=false\n"
        "Categories=System;\n"
        "EOF\n"
        "chmod 0755 /home/live/Desktop/linux-iso-installer.desktop\n"
        "chown -R live:users /home/live\n"
        "command -v baseSetRunlevel >/dev/null 2>&1 && baseSetRunlevel 5 || true\n"
        "command -v baseService >/dev/null 2>&1 && baseService sddm on || true\n"
        "command -v baseService >/dev/null 2>&1 && baseService NetworkManager on || true\n",
        encoding="utf-8",
    )
    config_sh.chmod(0o755)

    build_sh = destination / "build.sh"
    build_sh.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "HERE=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "OUT=${1:-$HERE/build-result}\n"
        "BACKEND=${LINUX_ISO_BUILD_BACKEND:-auto}\n"
        "mkdir -p \"$OUT\"\n"
        "if [ \"$BACKEND\" = auto ]; then\n"
        "  if command -v kiwi-boxbuild >/dev/null 2>&1 && command -v podman >/dev/null 2>&1; then BACKEND=boxbuild;\n"
        "  elif command -v kiwi-ng >/dev/null 2>&1 && command -v podman >/dev/null 2>&1 && { command -v qemu-system-x86_64 >/dev/null 2>&1 || command -v qemu-kvm >/dev/null 2>&1; }; then BACKEND=boxbuild;\n"
        "  elif command -v kiwi-ng >/dev/null 2>&1; then BACKEND=direct;\n"
        "  else echo 'No KIWI backend found. Run: linux-iso build-doctor' >&2; exit 2; fi\n"
        "fi\n"
        "echo \"Linux ISO - Suret build backend: $BACKEND\"\n"
        "if [ \"$BACKEND\" = boxbuild ]; then\n"
        f"  if command -v kiwi-boxbuild >/dev/null 2>&1; then exec kiwi-boxbuild --box {recipe.preferred_box} kiwi --description \"$HERE\" --target-dir \"$OUT\"; fi\n"
        f"  if command -v kiwi-ng >/dev/null 2>&1; then exec kiwi-ng system boxbuild --box {recipe.preferred_box} kiwi --description \"$HERE\" --target-dir \"$OUT\"; fi\n"
        "  echo 'boxbuild backend requested but neither kiwi-boxbuild nor kiwi-ng is available' >&2; exit 2\n"
        "fi\n"
        "if [ \"$BACKEND\" = direct ]; then\n"
        "  kiwi-ng image info --description \"$HERE\" --resolve-package-list > \"$OUT/package-resolution.txt\"\n"
        "  KIWI=$(command -v kiwi-ng)\n"
        "  exec sudo \"$KIWI\" system build --description \"$HERE\" --target-dir \"$OUT\"\n"
        "fi\n"
        "echo \"Unknown backend: $BACKEND\" >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    build_sh.chmod(0o755)

    qemu_sh = destination / "test-qemu.sh"
    qemu_sh.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "HERE=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "RESULT=${1:-$HERE/build-result}\n"
        "ISO=$(find \"$RESULT\" -maxdepth 2 -type f -name '*.iso' -print | sort | tail -n 1)\n"
        "if [ -z \"${ISO:-}\" ]; then echo \"No ISO found under $RESULT\" >&2; exit 2; fi\n"
        "QEMU=$(command -v qemu-system-x86_64 || command -v qemu-kvm || true)\n"
        "if [ -z \"$QEMU\" ]; then echo 'qemu-system-x86_64 not found' >&2; exit 2; fi\n"
        "ACCEL='-accel tcg'\n"
        "if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then ACCEL='-enable-kvm -cpu host'; fi\n"
        "echo \"Booting: $ISO\"\n"
        "exec $QEMU $ACCEL -m ${LINUX_ISO_QEMU_MEMORY:-6144} -smp ${LINUX_ISO_QEMU_CPUS:-4} "
        "-boot d -cdrom \"$ISO\" -device virtio-vga -display gtk\n",
        encoding="utf-8",
    )
    qemu_sh.chmod(0o755)


def _select_backend(requested: str = "auto") -> str:
    if requested not in {"auto", "boxbuild", "direct"}:
        raise BuilderError(f"Unknown build backend: {requested}")
    if requested == "boxbuild":
        standalone = shutil.which("kiwi-boxbuild") is not None
        core = shutil.which("kiwi-ng") is not None and (shutil.which("qemu-system-x86_64") is not None or shutil.which("qemu-kvm") is not None)
        if shutil.which("podman") is None:
            raise BuilderError("podman is required for boxbuild")
        if not standalone and not core:
            raise BuilderError("boxbuild requires kiwi-boxbuild, or kiwi-ng plus QEMU")
        return "boxbuild"
    if requested == "direct":
        if shutil.which("kiwi-ng") is None:
            raise BuilderError("kiwi-ng is not installed")
        return "direct"
    if shutil.which("podman") and (
        shutil.which("kiwi-boxbuild")
        or (shutil.which("kiwi-ng") and (shutil.which("qemu-system-x86_64") or shutil.which("qemu-kvm")))
    ):
        return "boxbuild"
    if shutil.which("kiwi-ng"):
        return "direct"
    raise BuilderError("No KIWI backend found; run 'linux-iso build-doctor' for details")


def run_kiwi_build(project: Path, backend: str = "auto") -> int:
    project = project.expanduser().resolve()
    if not (project / "config.xml").is_file():
        raise BuilderError(f"Not a staged KIWI project: {project}")
    selected = _select_backend(backend)
    env = dict(**__import__("os").environ)
    env["LINUX_ISO_BUILD_BACKEND"] = selected
    proc = subprocess.run([str(project / "build.sh")], cwd=project, env=env, check=False)
    return proc.returncode


def generate_kiwi_project(
    profile: Path,
    destination: Path,
    recipe_id: str = UBUNTU_2604_KDE.id,
) -> Path:
    profile = profile.expanduser().resolve()
    destination = destination.expanduser().resolve()
    manifest = _read_manifest(profile)
    verification = verify_profile(profile)
    if not verification.ok:
        detail = "; ".join(verification.errors[:4])
        if len(verification.errors) > 4:
            detail += f"; ... {len(verification.errors) - 4} more"
        raise BuilderError(f"Profile verification failed before ISO staging: {detail}")
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
    _write_build_scripts(destination, recipe)
    _write_config_xml(destination / "config.xml", recipe, manifest)

    from linux_iso.portability import portability_report
    portability = portability_report(profile, recipe_id=recipe_id)
    if not portability.ready:
        detail = "; ".join(portability.blockers[:4])
        raise BuilderError(f"Profile portability check failed before ISO staging: {detail}")
    (destination / "PORTABILITY.txt").write_text(portability.render() + "\n", encoding="utf-8")

    required = _required_base_packages(manifest)
    marker = destination / "README-BUILDER.txt"
    marker.write_text(
        f"{PRODUCT_NAME} v{__version__} KIWI project\n"
        f"Recipe: {recipe.id}\n"
        f"Target Plasma: {recipe.target_plasma_version or 'unknown'}\n"
        f"Appearance packages embedded in base image: {len(required)}\n"
        "Live user: live (ephemeral media only)\n"
        "The captured profile is applied to the live session and again to the user created by Calamares.\n"
        "Run ./build.sh to build, then ./test-qemu.sh to boot the generated ISO.\n"
        "The generated recipe remains experimental until boot/install validation in QEMU succeeds.\n",
        encoding="utf-8",
    )
    return destination


def generate_kiwi_overlay(profile: Path, destination: Path) -> Path:
    """Backward-compatible name; v0.2+ stages a full KIWI project."""
    return generate_kiwi_project(profile, destination)
