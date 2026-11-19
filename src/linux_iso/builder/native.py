from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import yaml

from linux_iso.verification import verify_profile


class NativeIsoError(RuntimeError):
    pass


@dataclass
class NativeIsoProbe:
    base_iso: str
    distro_id: str
    distro_name: str
    distro_version: str | None
    architecture: str
    package_family: str
    live_rootfs: str
    kernel: str | None
    initrd: str | None
    installer: str
    desktop_hint: str | None = None
    boot_family: str = "grub"
    supports_native_build: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


PARDUS_KDE_PACKAGES = [
    "kde-plasma-desktop",
    "sddm",
    "plasma-nm",
    "plasma-pa",
    "powerdevil",
    "dolphin",
    "konsole",
    "systemsettings",
    "kinfocenter",
    "plasma-discover",
    "xdg-desktop-portal-kde",
    "kde-config-sddm",
    "breeze-cursor-theme",
    "flatpak",
]

PARDUS_XFCE_REMOVE_PACKAGES = [
    "pardus-xfce-desktop",
    "xfce4",
    "xfce4-session",
    "xfdesktop4",
    "xfce4-panel",
    "lightdm",
    "lightdm-gtk-greeter",
]

# Vendor applications captured as native packages often relied on a third-party
# repository on the source machine. An official base ISO does not necessarily
# carry those repository definitions. Native Mode resolves these known apps to
# distro-neutral Flatpak IDs instead of leaving a favorite that cannot launch.
PORTABLE_FLATPAK_FALLBACKS = {
    "code": "com.visualstudio.code",
    "visual-studio-code": "com.visualstudio.code",
    "signal-desktop": "org.signal.Signal",
    "steam": "com.valvesoftware.Steam",
    "steam-launcher": "com.valvesoftware.Steam",
    "discord": "com.discordapp.Discord",
    "spotify-client": "com.spotify.Client",
    "obs-studio": "com.obsproject.Studio",
    "brave-browser": "com.brave.Browser",
    "google-chrome-stable": "com.google.Chrome",
}

ROOTFS_CANDIDATES = (
    "/live/filesystem.squashfs",
    "/casper/filesystem.squashfs",
    "/LiveOS/squashfs.img",
)


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeIsoError(f"Command failed: {' '.join(command)}: {exc}") from exc


def _require_tools(names: Iterable[str]) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise NativeIsoError(
            "Native ISO mode requires: " + ", ".join(missing) + ". "
            "Install the missing tools and retry."
        )


def _list_iso(iso: Path) -> set[str]:
    _require_tools(["xorriso"])
    proc = _run(["xorriso", "-indev", str(iso), "-find", "/", "-type", "f", "-print"], timeout=180)
    if proc.returncode != 0:
        raise NativeIsoError(f"Could not inspect ISO with xorriso: {proc.stderr.strip()}")
    result: set[str] = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("'") and line.endswith("'"):
            line = line[1:-1]
        if line.startswith("/"):
            result.add(line)
    return result


def _extract_small_file(iso: Path, source: str) -> str | None:
    _require_tools(["xorriso"])
    with tempfile.TemporaryDirectory(prefix="suret-iso-probe-") as tmp:
        target = Path(tmp) / Path(source).name
        proc = _run(
            ["xorriso", "-osirrox", "on", "-indev", str(iso), "-extract", source, str(target)],
            timeout=60,
        )
        if proc.returncode != 0 or not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None


def _probe_from_file_set(base: Path, files: set[str], info_text: str | None = None) -> NativeIsoProbe:
    rootfs = next((item for item in ROOTFS_CANDIDATES if item in files), None)
    if rootfs is None:
        raise NativeIsoError(
            "Unsupported live ISO layout. Expected one of: " + ", ".join(ROOTFS_CANDIDATES)
        )

    info = (info_text or "").strip()
    lower = f"{base.name} {info}".lower()
    distro_id = "unknown"
    distro_name = info or base.stem
    distro_version: str | None = None
    package_family = "unknown"
    installer = "unknown"
    desktop_hint: str | None = None
    supports = False

    if "pardus" in lower:
        distro_id = "pardus"
        distro_name = info or "Pardus"
        package_family = "apt"
        installer = "pardus-installer"
        supports = rootfs == "/live/filesystem.squashfs"
        match = re.search(r"pardus[- ]?(\d+(?:\.\d+)?)", lower, re.I)
        if match:
            distro_version = match.group(1)
        if "xfce" in lower:
            desktop_hint = "xfce"
        elif "gnome" in lower:
            desktop_hint = "gnome"
    elif "ubuntu" in lower or rootfs.startswith("/casper/"):
        distro_id = "ubuntu"
        distro_name = info or "Ubuntu"
        package_family = "apt"
        installer = "native-ubuntu"
        match = re.search(r"(\d{2}\.\d{2})", lower)
        if match:
            distro_version = match.group(1)
    elif "fedora" in lower or rootfs.startswith("/LiveOS/"):
        distro_id = "fedora"
        distro_name = info or "Fedora"
        package_family = "dnf"
        installer = "anaconda"
        match = re.search(r"fedora[^0-9]*(\d+)", lower)
        if match:
            distro_version = match.group(1)

    kernel = None
    initrd = None
    for candidate in ("/live/vmlinuz", "/casper/vmlinuz", "/images/pxeboot/vmlinuz"):
        if candidate in files:
            kernel = candidate
            break
    for candidate in ("/live/initrd.img", "/casper/initrd", "/images/pxeboot/initrd.img"):
        if candidate in files:
            initrd = candidate
            break

    architecture = "x86_64" if any(token in lower for token in ("amd64", "x86_64")) else "unknown"
    return NativeIsoProbe(
        base_iso=str(base),
        distro_id=distro_id,
        distro_name=distro_name,
        distro_version=distro_version,
        architecture=architecture,
        package_family=package_family,
        live_rootfs=rootfs,
        kernel=kernel,
        initrd=initrd,
        installer=installer,
        desktop_hint=desktop_hint,
        supports_native_build=supports,
    )


def probe_iso_tree(tree: Path, *, label: str | None = None) -> NativeIsoProbe:
    """Probe an already extracted ISO tree. Primarily useful for tests and diagnostics."""
    tree = tree.resolve()
    if not tree.is_dir():
        raise NativeIsoError(f"ISO tree not found: {tree}")
    files = {"/" + p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file()}
    info_path = tree / ".disk/info"
    info = info_path.read_text(encoding="utf-8", errors="replace") if info_path.is_file() else label
    return _probe_from_file_set(Path(label or tree.name), files, info)


def probe_native_iso(base_iso: Path) -> NativeIsoProbe:
    base_iso = base_iso.expanduser().resolve()
    if not base_iso.is_file():
        raise NativeIsoError(f"Base ISO not found: {base_iso}")
    files = _list_iso(base_iso)
    info = _extract_small_file(base_iso, "/.disk/info")
    return _probe_from_file_set(base_iso, files, info)


def _load_manifest(profile: Path) -> dict:
    manifest_path = profile / "manifest.yaml"
    if not manifest_path.is_file():
        raise NativeIsoError(f"Profile manifest not found: {manifest_path}")
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


def _profile_app_plan(manifest: dict, package_family: str) -> tuple[list[str], list[str]]:
    native: list[str] = []
    flatpaks: list[str] = []
    for item in manifest.get("packages", []):
        if not item.get("installer_visible", True):
            continue
        if item.get("required_for_appearance"):
            continue
        provider = str(item.get("provider") or "")
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        if provider == package_family:
            fallback = PORTABLE_FLATPAK_FALLBACKS.get(name)
            if fallback:
                if fallback not in flatpaks:
                    flatpaks.append(fallback)
                continue
            if name not in native:
                native.append(name)
        elif provider == "flatpak" and name not in flatpaks:
            flatpaks.append(name)
    return native, flatpaks


def _restore_native_launcher_execs(profile_copy: Path) -> int:
    """Undo generic cross-distro launcher translations for native builds.

    Capture keeps a reversible X-Suret-Original-Exec-B64 marker whenever it
    translates an Exec line. In a same-distro native remaster, distro-native
    commands (for example pardus-about and pardus-mycomputer) should remain
    native. Portable web/Flatpak replacements are intentionally retained.
    """
    count = 0
    payload = profile_copy / "payload"
    if not payload.is_dir():
        return 0
    for path in payload.rglob("*.desktop"):
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = raw.splitlines(keepends=True)
        out: list[str] = []
        i = 0
        changed = False
        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip("\r\n")
            if stripped.startswith("Exec=") and i + 1 < len(lines):
                marker = lines[i + 1].rstrip("\r\n")
                prefix = "X-Suret-Original-Exec-B64="
                if marker.startswith(prefix):
                    current = stripped.split("=", 1)[1].strip()
                    encoded = marker[len(prefix):].strip()
                    try:
                        original = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
                    except (ValueError, UnicodeDecodeError):
                        original = ""
                    # Web-app and vendor fallback launchers are deliberately
                    # portable. Everything else can use its original command
                    # because source and base distro are identical in Native Mode.
                    portable = current.startswith("xdg-open ") or current.startswith("flatpak run ")
                    newline = line[len(stripped):]
                    out.append(line if portable or not original else f"Exec={original}{newline}")
                    i += 2  # Drop the Suret-only metadata line from final profile.
                    if original and not portable:
                        count += 1
                    changed = True
                    continue
            out.append(line)
            i += 1
        if changed:
            path.write_text("".join(out), encoding="utf-8")
    return count


def _safe_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


NATIVE_FIRST_LOGIN = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

PROFILE = Path("/usr/share/linux-iso/profile")
STATE = PROFILE / "native-restore.json"
MARKER = Path.home() / ".local/state/linux-iso/native-profile-v1.done"
TEXT_SUFFIXES = {"", ".conf", ".ini", ".rc", ".list", ".desktop", ".profile", ".toml", ".fish", ".zsh", ".bash", ".json", ".xml", ".qml"}


def rewrite_home(path: Path, home: Path) -> None:
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        return
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    updated = raw.replace("{{HOME}}", str(home))
    if updated != raw:
        path.write_text(updated, encoding="utf-8")


def run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass


def main() -> int:
    if MARKER.exists() or not STATE.is_file():
        return 0
    home = Path.home().resolve()
    data = json.loads(STATE.read_text(encoding="utf-8"))
    payload = PROFILE / "payload/home"
    if payload.is_dir():
        for src in payload.rglob("*"):
            rel = src.relative_to(payload)
            dst = home / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            rewrite_home(dst, home)

    avatar = home / ".face"
    if avatar.is_file():
        run(["dbus-send", "--system", "--dest=org.freedesktop.Accounts", "--type=method_call", "/org/freedesktop/Accounts", "org.freedesktop.Accounts.FindUserByName", f"string:{os.environ.get('USER','')}"])

    run(["kbuildsycoca6"])
    run(["kbuildsycoca5"])
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text("ok\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

NATIVE_PRELOGIN = r'''#!/usr/bin/env python3
from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from pathlib import Path

PROFILE = Path("/usr/share/linux-iso/profile")
PAYLOAD = PROFILE / "payload/home"
TEXT_SUFFIXES = {"", ".conf", ".ini", ".rc", ".list", ".desktop", ".profile", ".toml", ".fish", ".zsh", ".bash", ".json", ".xml", ".qml"}


def rewrite_home(path: Path, home: Path) -> None:
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        return
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    updated = raw.replace("{{HOME}}", str(home))
    if updated != raw:
        path.write_text(updated, encoding="utf-8")


def copy_profile(home: Path, uid: int, gid: int, username: str) -> None:
    marker = home / ".local/state/linux-iso/native-prelogin-v1.done"
    if marker.exists() or not PAYLOAD.is_dir():
        return
    for src in PAYLOAD.rglob("*"):
        rel = src.relative_to(PAYLOAD)
        dst = home / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            rewrite_home(dst, home)
    for path in [home, *home.rglob("*")]:
        try:
            os.chown(path, uid, gid)
        except OSError:
            pass
    avatar = home / ".face"
    if avatar.is_file():
        icons = Path("/var/lib/AccountsService/icons")
        users = Path("/var/lib/AccountsService/users")
        try:
            icons.mkdir(parents=True, exist_ok=True)
            users.mkdir(parents=True, exist_ok=True)
            icon_dst = icons / username
            shutil.copy2(avatar, icon_dst)
            os.chmod(icon_dst, 0o644)
            user_file = users / username
            current = user_file.read_text(encoding="utf-8", errors="replace") if user_file.is_file() else "[User]\n"
            lines = [line for line in current.splitlines() if not line.startswith("Icon=")]
            if not lines or lines[0].strip() != "[User]":
                lines.insert(0, "[User]")
            lines.append(f"Icon={icon_dst}")
            user_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
    # User-local fonts must be visible before the first Plasma session paints
    # panel text (for example the digital-clock font).
    if (home / ".local/share/fonts").is_dir() or (home / ".fonts").is_dir():
        try:
            subprocess.run(["runuser", "-u", username, "--", "fc-cache", "-f"], check=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("ok\n", encoding="utf-8")
    try:
        os.chown(marker.parent, uid, gid)
        os.chown(marker, uid, gid)
    except OSError:
        pass


def main() -> int:
    try:
        cmdline = Path("/proc/cmdline").read_text(encoding="utf-8", errors="replace")
    except OSError:
        cmdline = ""
    if Path("/run/live/medium").exists() or "boot=live" in cmdline:
        return 0
    for entry in pwd.getpwall():
        if not (1000 <= entry.pw_uid < 60000):
            continue
        home = Path(entry.pw_dir)
        if home.is_dir():
            copy_profile(home, entry.pw_uid, entry.pw_gid, entry.pw_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


NATIVE_PRELOGIN_SERVICE = '''[Unit]
Description=Apply Suret native desktop profile before first graphical login
After=local-fs.target
Before=display-manager.service
ConditionPathExists=/usr/share/linux-iso/profile/manifest.yaml

[Service]
Type=oneshot
ExecStart=/usr/lib/linux-iso/native-prelogin.py
RemainAfterExit=yes

[Install]
WantedBy=graphical.target
'''


NATIVE_SYSTEM_VISUAL = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PROFILE = Path("/usr/share/linux-iso/profile")
META = PROFILE / "system-visual.json"
PAYLOAD = PROFILE / "payload/system"


def copy_tree(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if dst.exists():
        shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return True


def main() -> int:
    if not META.is_file():
        return 0
    data = json.loads(META.read_text(encoding="utf-8"))
    grub = data.get("grub") or {}
    settings = grub.get("settings") or {}
    grub_lines = []
    if grub.get("theme_captured") and copy_tree(PAYLOAD / "grub/theme", Path("/boot/grub/themes/suret-source")):
        theme_file = grub.get("theme_file") or "theme.txt"
        grub_lines.append(f'GRUB_THEME="/boot/grub/themes/suret-source/{theme_file}"')
    bg_files = list((PAYLOAD / "grub").glob("background.*")) if (PAYLOAD / "grub").is_dir() else []
    if bg_files:
        bg_dst = Path("/boot/grub") / ("suret-source-background" + bg_files[0].suffix)
        shutil.copy2(bg_files[0], bg_dst)
        grub_lines.append(f'GRUB_BACKGROUND="{bg_dst}"')
    for key in ("GRUB_GFXMODE", "GRUB_GFXPAYLOAD_LINUX", "GRUB_TIMEOUT_STYLE", "GRUB_TIMEOUT"):
        value = settings.get(key)
        if value not in (None, ""):
            grub_lines.append(f'{key}="{value}"')
    if grub_lines:
        cfg = Path("/etc/default/grub.d/90-suret-visual.cfg")
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("\n".join(grub_lines) + "\n", encoding="utf-8")

    sddm = data.get("sddm") or {}
    sddm_settings = sddm.get("settings") or {}

    # SDDM runs before a user home is active. Promote the captured active
    # cursor theme and fonts to system-visible locations so the login screen
    # does not briefly use a different cursor/font and then switch at login.
    cursor = sddm_settings.get("CursorTheme")
    if cursor:
        for candidate in (
            PROFILE / "payload/home/.local/share/icons" / cursor,
            PROFILE / "payload/home/.icons" / cursor,
        ):
            if candidate.is_dir():
                copy_tree(candidate, Path("/usr/share/icons") / cursor)
                break
    fonts_src = PROFILE / "payload/home/.local/share/fonts"
    if fonts_src.is_dir():
        copy_tree(fonts_src, Path("/usr/local/share/fonts/suret-profile"))
        try:
            subprocess.run(["fc-cache", "-f"], check=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass

    sddm_lines = ["[Theme]"]
    if sddm.get("theme_captured") and copy_tree(PAYLOAD / "sddm/theme", Path("/usr/share/sddm/themes/suret-source")):
        sddm_lines.append("Current=suret-source")
    font = sddm_settings.get("Font")
    if cursor:
        sddm_lines.append(f"CursorTheme={cursor}")
    if font:
        sddm_lines.append(f"Font={font}")
    if len(sddm_lines) > 1:
        cfg = Path("/etc/sddm.conf.d/80-suret-source-theme.conf")
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("\n".join(sddm_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


NATIVE_BUILD_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd)
META="$HERE/native.json"
BASE_ISO=${LINUX_ISO_BASE_ISO:-"__BASE_ISO__"}
RESULT=${LINUX_ISO_NATIVE_RESULT:-"__RESULT__"}
WORK=${LINUX_ISO_NATIVE_WORK:-"$HERE/work"}
ISO_ROOT="$WORK/iso-root"
ROOTFS="$WORK/rootfs"
ROOTFS_REL="__ROOTFS_REL__"
PROFILE="$HERE/profile"
OUT_ISO="$RESULT/__OUTPUT_NAME__"
REPLACE_DESKTOP=__REPLACE_DESKTOP__

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required tool: $1" >&2; exit 2; }; }
for tool in xorriso unsquashfs mksquashfs rsync chroot mount umount; do need "$tool"; done
[[ -f "$BASE_ISO" ]] || { echo "Base ISO not found: $BASE_ISO" >&2; exit 2; }

sudo -v
mkdir -p "$RESULT"
sudo rm -rf "$WORK"
mkdir -p "$WORK" "$ISO_ROOT" "$ROOTFS"

echo "[1/7] Extracting native base ISO"
xorriso -osirrox on -indev "$BASE_ISO" -extract / "$ISO_ROOT"

echo "[2/7] Unpacking native live filesystem: $ROOTFS_REL"
[[ -f "$ISO_ROOT/$ROOTFS_REL" ]] || { echo "Live rootfs not found: $ISO_ROOT/$ROOTFS_REL" >&2; exit 3; }
sudo unsquashfs -f -d "$ROOTFS" "$ISO_ROOT/$ROOTFS_REL"

echo "[3/7] Injecting Suret profile and first-login convergence"
sudo mkdir -p "$ROOTFS/usr/share/linux-iso/profile" "$ROOTFS/usr/lib/linux-iso" "$ROOTFS/etc/xdg/autostart"
sudo rsync -a --delete "$PROFILE/" "$ROOTFS/usr/share/linux-iso/profile/"
sudo install -m 0755 "$HERE/native-first-login.py" "$ROOTFS/usr/lib/linux-iso/native-first-login.py"
sudo install -m 0755 "$HERE/native-prelogin.py" "$ROOTFS/usr/lib/linux-iso/native-prelogin.py"
sudo install -m 0755 "$HERE/native-system-visual.py" "$ROOTFS/usr/lib/linux-iso/native-system-visual.py"
sudo install -m 0644 "$HERE/linux-iso-native-first-login.desktop" "$ROOTFS/etc/xdg/autostart/linux-iso-native-first-login.desktop"
sudo install -m 0644 "$HERE/linux-iso-native-prelogin.service" "$ROOTFS/etc/systemd/system/linux-iso-native-prelogin.service"
sudo mkdir -p "$ROOTFS/etc/systemd/system/graphical.target.wants"
sudo ln -sfn /etc/systemd/system/linux-iso-native-prelogin.service "$ROOTFS/etc/systemd/system/graphical.target.wants/linux-iso-native-prelogin.service"
sudo chroot "$ROOTFS" /usr/lib/linux-iso/native-system-visual.py || true

cleanup_mounts() {
  set +e
  for path in run sys proc dev; do sudo umount -l "$ROOTFS/$path" >/dev/null 2>&1 || true; done
}
trap cleanup_mounts EXIT

for path in dev proc sys run; do sudo mkdir -p "$ROOTFS/$path"; done
sudo mount --bind /dev "$ROOTFS/dev"
sudo mount -t proc proc "$ROOTFS/proc"
sudo mount --rbind /sys "$ROOTFS/sys"
sudo mount --make-rslave "$ROOTFS/sys"
sudo mount --rbind /run "$ROOTFS/run"
sudo mount --make-rslave "$ROOTFS/run"
sudo cp -a "$ROOTFS/etc/resolv.conf" "$ROOTFS/etc/resolv.conf.suret-backup" 2>/dev/null || true
sudo rm -f "$ROOTFS/etc/resolv.conf"
sudo cp -L /etc/resolv.conf "$ROOTFS/etc/resolv.conf"

echo "[4/7] Installing target desktop and source applications inside native distro"
sudo cp "$HERE/native-install.sh" "$ROOTFS/tmp/linux-iso-native-install.sh"
sudo chmod 0755 "$ROOTFS/tmp/linux-iso-native-install.sh"
sudo chroot "$ROOTFS" /usr/bin/env REPLACE_DESKTOP="$REPLACE_DESKTOP" /bin/bash /tmp/linux-iso-native-install.sh
sudo rm -f "$ROOTFS/tmp/linux-iso-native-install.sh"
sudo rm -f "$ROOTFS/etc/resolv.conf"
if [[ -e "$ROOTFS/etc/resolv.conf.suret-backup" || -L "$ROOTFS/etc/resolv.conf.suret-backup" ]]; then
  sudo mv "$ROOTFS/etc/resolv.conf.suret-backup" "$ROOTFS/etc/resolv.conf"
fi
cleanup_mounts
trap - EXIT

echo "[5/7] Refreshing live metadata"
if command -v dpkg-query >/dev/null 2>&1; then :; fi
sudo chroot "$ROOTFS" dpkg-query -W -f='${Package} ${Version}\n' | sudo tee "$ISO_ROOT/live/filesystem.packages" >/dev/null || true
COMP=$(unsquashfs -s "$ISO_ROOT/$ROOTFS_REL" 2>/dev/null | awk -F': ' '/Compression/{print $2; exit}' | awk '{print $1}')
[[ -n "$COMP" ]] || COMP=xz
sudo rm -f "$ISO_ROOT/$ROOTFS_REL"
sudo mksquashfs "$ROOTFS" "$ISO_ROOT/$ROOTFS_REL" -noappend -comp "$COMP"

if [[ -f "$ISO_ROOT/md5sum.txt" ]]; then
  echo "[6/7] Regenerating ISO checksums"
  (cd "$ISO_ROOT" && find . -type f ! -name md5sum.txt -print0 | sort -z | xargs -0 md5sum) | sudo tee "$ISO_ROOT/md5sum.txt" >/dev/null
else
  echo "[6/7] No md5sum.txt in base ISO; preserving native metadata"
fi

echo "[7/7] Replaying native boot catalog and writing ISO"
rm -f "$OUT_ISO"
xorriso -indev "$BASE_ISO" -outdev "$OUT_ISO" -map "$ISO_ROOT" / -boot_image any replay -commit

echo "Native ISO ready: $OUT_ISO"
echo "This image retains the base distro's bootloader, installer, repositories and OS identity."
'''


NATIVE_INSTALL_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
DISTRO_ID=__DISTRO_ID__

log() { printf '[native] %s\n' "$*"; }

ensure_native_network_sources() {
  [[ "$DISTRO_ID" == "pardus" ]] || return 0
  if grep -RhsE '^[[:space:]]*(deb[[:space:]]+https?://|URIs:[[:space:]]+https?://)' \
       /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null | grep -qi 'pardus'; then
    return 0
  fi
  log "No Pardus network repository was found in the live rootfs; adding official Pardus 25 sources"
  mkdir -p /etc/apt/sources.list.d
  cat > /etc/apt/sources.list.d/99-suret-pardus-native.list <<'EOS'
deb http://depo.pardus.org.tr/pardus yirmibes main contrib non-free non-free-firmware
deb http://depo.pardus.org.tr/pardus yirmibes-deb main contrib non-free non-free-firmware
deb http://depo.pardus.org.tr/guvenlik yirmibes-deb main contrib non-free non-free-firmware
EOS
}

if command -v apt-get >/dev/null 2>&1; then
  ensure_native_network_sources
  log "Refreshing native APT metadata"
  apt-get update

  desktop_pkgs=(__DESKTOP_PACKAGES__)
  log "Installing KDE/Plasma into the native distro"
  for pkg in "${desktop_pkgs[@]}"; do
    if apt-cache show "$pkg" >/dev/null 2>&1; then
      apt-get install -y --no-install-recommends "$pkg" || log "warning: could not install $pkg"
    else
      log "warning: native repository does not provide $pkg"
    fi
  done

  if [[ "${REPLACE_DESKTOP:-0}" == "1" ]]; then
    remove_pkgs=(__REMOVE_PACKAGES__)
    log "Removing the base desktop session while keeping the native distro"
    apt-get purge -y "${remove_pkgs[@]}" || true
    apt-get autoremove -y || true
  fi

  native_apps=(__NATIVE_APPS__)
  log "Installing captured native applications when available in the base distro repositories"
  for pkg in "${native_apps[@]}"; do
    if apt-cache show "$pkg" >/dev/null 2>&1; then
      apt-get install -y "$pkg" || log "warning: could not install $pkg"
    else
      log "skip unavailable native package: $pkg"
    fi
  done

  if command -v debconf-set-selections >/dev/null 2>&1 && apt-cache show sddm >/dev/null 2>&1; then
    printf 'sddm shared/default-x-display-manager select sddm\n' | debconf-set-selections || true
  fi
  if [[ -e /lib/systemd/system/sddm.service ]]; then
    mkdir -p /etc/systemd/system /etc/sddm.conf.d /etc/systemd/system/sddm.service.d
    ln -sfn /lib/systemd/system/sddm.service /etc/systemd/system/display-manager.service
    cat > /usr/lib/linux-iso/sddm-live-prepare <<'EOS'
#!/bin/sh
set -eu
if grep -qw 'boot=live' /proc/cmdline || [ -d /run/live/medium ]; then
    user=$(awk -F: '$3 >= 1000 && $3 < 60000 { print $1; exit }' /etc/passwd || true)
    [ -n "$user" ] || exit 0
    session=plasma
    [ -f /usr/share/wayland-sessions/plasma.desktop ] && session=plasma
    cat > /etc/sddm.conf.d/99-suret-live.conf <<EOF
[Autologin]
User=$user
Session=$session
Relogin=true
EOF
else
    rm -f /etc/sddm.conf.d/99-suret-live.conf
fi
EOS
    chmod 0755 /usr/lib/linux-iso/sddm-live-prepare
    cat > /etc/systemd/system/sddm.service.d/20-suret-live.conf <<'EOS'
[Service]
ExecStartPre=/usr/lib/linux-iso/sddm-live-prepare
EOS
  fi
  update-initramfs -u -k all || true
  apt-get clean
fi

flatpaks=(__FLATPAKS__)
if (( ${#flatpaks[@]} > 0 )) && command -v flatpak >/dev/null 2>&1; then
  flatpak remote-add --system --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo || true
  for app in "${flatpaks[@]}"; do
    if ! flatpak install --system -y flathub "$app"; then
      log "ERROR: required captured application could not be installed: $app"
      exit 31
    fi
  done
fi

# Ensure the live and installed user both receive the captured KDE state on first login.
mkdir -p /etc/xdg/autostart
# Keep the native distro identity and installer packages intact.
exit 0
'''


NATIVE_QEMU_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
RESULT=${1:-__RESULT__}
ISO=$(find "$RESULT" -maxdepth 1 -type f -name '*.iso' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)
[[ -n "$ISO" && -f "$ISO" ]] || { echo "No native ISO found in $RESULT" >&2; exit 2; }
QEMU=$(command -v qemu-system-x86_64 || command -v qemu-kvm || true)
[[ -n "$QEMU" ]] || { echo "qemu-system-x86_64 not found" >&2; exit 2; }
DISK="$RESULT/linux-iso-native-test.qcow2"
command -v qemu-img >/dev/null 2>&1 || { echo "qemu-img not found" >&2; exit 2; }
rm -f "$DISK"
qemu-img create -f qcow2 "$DISK" 40G
ACCEL=(-accel tcg,thread=multi -cpu max,la57=off)
if [[ -r /dev/kvm && -w /dev/kvm ]]; then ACCEL=(-enable-kvm -cpu host); fi
CODE=""; VARS=""
for f in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/ovmf/OVMF.fd; do [[ -f "$f" ]] && CODE="$f" && break; done
for f in /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd; do [[ -f "$f" ]] && VARS="$f" && break; done
args=(-machine q35 "${ACCEL[@]}" -m 4096 -smp 2 -boot once=d,menu=on -drive "file=$DISK,format=qcow2,if=virtio" -cdrom "$ISO" -netdev user,id=net0 -device virtio-net-pci,netdev=net0 -display gtk,gl=off -name "Suret - NATIVE INSTALL / then INSTALLED SYSTEM")
if [[ -n "$CODE" && -n "$VARS" ]]; then
  VARS_COPY="$RESULT/linux-iso-native-OVMF_VARS.fd"; cp "$VARS" "$VARS_COPY"
  args+=( -drive "if=pflash,format=raw,readonly=on,file=$CODE" -drive "if=pflash,format=raw,file=$VARS_COPY" )
fi
exec "$QEMU" "${args[@]}"
'''


def _shell_array(items: list[str]) -> str:
    import shlex
    return " ".join(shlex.quote(x) for x in items)


def stage_native_project(
    profile: Path,
    base_iso: Path,
    output: Path,
    *,
    result: Path | None = None,
    replace_desktop: bool = False,
) -> Path:
    profile = profile.expanduser().resolve()
    base_iso = base_iso.expanduser().resolve()
    output = output.expanduser().resolve()
    result = (result or (output.parent / "linux-iso-native-result")).expanduser().resolve()

    verification = verify_profile(profile)
    if not verification.ok:
        raise NativeIsoError("Profile verification failed; run `linux-iso verify` first.")

    probe = probe_native_iso(base_iso)
    if not probe.supports_native_build:
        raise NativeIsoError(
            f"Native build adapter is not ready for {probe.distro_id}/{probe.live_rootfs}. "
            "Pardus/Debian live ISOs using /live/filesystem.squashfs are supported first."
        )

    manifest = _load_manifest(profile)
    source = manifest.get("source", {})
    source_id = str(source.get("distro_id") or "").lower()
    if source_id and source_id != probe.distro_id:
        raise NativeIsoError(
            f"Source profile distro is {source_id!r}, but base ISO is {probe.distro_id!r}. "
            "Native mode intentionally refuses silent cross-distro grafting."
        )
    desktop = str((manifest.get("desktop") or {}).get("desktop") or "unknown")
    if desktop != "kde-plasma":
        raise NativeIsoError(
            f"The first native adapter currently targets KDE Plasma profiles; got {desktop!r}."
        )

    native_apps, flatpaks = _profile_app_plan(manifest, probe.package_family)
    output.mkdir(parents=True, exist_ok=True)
    staged_profile = output / "profile"
    shutil.copytree(profile, staged_profile, dirs_exist_ok=True)
    restored_native_launchers = _restore_native_launcher_execs(staged_profile)

    state = {
        "mode": "native-iso",
        "probe": probe.to_dict(),
        "profile": str(profile),
        "base_iso": str(base_iso),
        "result": str(result),
        "target_desktop": desktop,
        "replace_base_desktop": bool(replace_desktop),
        "native_apps": native_apps,
        "flatpaks": flatpaks,
        "restored_native_launchers": restored_native_launchers,
    }
    (output / "native.json").write_text(_safe_json(state), encoding="utf-8")
    (output / "profile/native-restore.json").write_text(_safe_json({"schema": 1, "desktop": desktop}), encoding="utf-8")
    (output / "native-first-login.py").write_text(NATIVE_FIRST_LOGIN, encoding="utf-8")
    (output / "native-prelogin.py").write_text(NATIVE_PRELOGIN, encoding="utf-8")
    (output / "native-system-visual.py").write_text(NATIVE_SYSTEM_VISUAL, encoding="utf-8")
    (output / "linux-iso-native-prelogin.service").write_text(NATIVE_PRELOGIN_SERVICE, encoding="utf-8")
    (output / "linux-iso-native-first-login.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Suret profile convergence\n"
        "Exec=/usr/lib/linux-iso/native-first-login.py\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )

    desktop_packages = PARDUS_KDE_PACKAGES if probe.distro_id == "pardus" else []
    install_script = NATIVE_INSTALL_SCRIPT
    install_script = install_script.replace("__DISTRO_ID__", probe.distro_id)
    install_script = install_script.replace("__DESKTOP_PACKAGES__", _shell_array(desktop_packages))
    install_script = install_script.replace("__REMOVE_PACKAGES__", _shell_array(PARDUS_XFCE_REMOVE_PACKAGES))
    install_script = install_script.replace("__NATIVE_APPS__", _shell_array(native_apps))
    install_script = install_script.replace("__FLATPAKS__", _shell_array(flatpaks))
    (output / "native-install.sh").write_text(install_script, encoding="utf-8")

    output_name = f"suret-{probe.distro_id}-{probe.distro_version or 'native'}-kde-amd64.iso"
    build_script = NATIVE_BUILD_SCRIPT
    build_script = build_script.replace("__BASE_ISO__", str(base_iso))
    build_script = build_script.replace("__RESULT__", str(result))
    build_script = build_script.replace("__ROOTFS_REL__", probe.live_rootfs.lstrip("/"))
    build_script = build_script.replace("__OUTPUT_NAME__", output_name)
    build_script = build_script.replace("__REPLACE_DESKTOP__", "1" if replace_desktop else "0")
    (output / "build-native.sh").write_text(build_script, encoding="utf-8")

    qemu = NATIVE_QEMU_SCRIPT.replace("__RESULT__", str(result))
    (output / "test-native-qemu.sh").write_text(qemu, encoding="utf-8")
    for path in (output / "build-native.sh", output / "native-install.sh", output / "native-first-login.py", output / "native-prelogin.py", output / "native-system-visual.py", output / "test-native-qemu.sh"):
        path.chmod(0o755)
    return output


def run_native_build(project: Path) -> int:
    project = project.expanduser().resolve()
    script = project / "build-native.sh"
    if not script.is_file():
        raise NativeIsoError(f"Native build script not found: {script}")
    proc = subprocess.run([str(script)], cwd=project, check=False)
    return int(proc.returncode)
