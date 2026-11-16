from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path


def parse_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in raw or raw.lstrip().startswith("#"):
                continue
            key, value = raw.split("=", 1)
            data[key] = value.strip().strip('"')
    except OSError:
        pass
    return data


def run_text(command: list[str]) -> str | None:
    if not command or shutil.which(command[0]) is None:
        return None
    try:
        proc = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def detect_desktop() -> tuple[str, str | None]:
    raw = " ".join(
        filter(
            None,
            [
                os.environ.get("XDG_CURRENT_DESKTOP"),
                os.environ.get("XDG_SESSION_DESKTOP"),
                os.environ.get("DESKTOP_SESSION"),
            ],
        )
    ).lower()

    if "kde" in raw or "plasma" in raw:
        version = run_text(["plasmashell", "--version"])
        return "kde-plasma", version
    if "gnome" in raw:
        return "gnome", run_text(["gnome-shell", "--version"])
    if "xfce" in raw:
        return "xfce", None
    if "cinnamon" in raw:
        return "cinnamon", None
    return raw.strip() or "unknown", None


def collect_system_info() -> dict[str, str | None]:
    release = parse_os_release()
    return {
        "distro_id": release.get("ID"),
        "distro_name": release.get("PRETTY_NAME") or release.get("NAME"),
        "distro_version": release.get("VERSION_ID"),
        "distro_like": release.get("ID_LIKE"),
        "kernel": platform.release(),
        "architecture": platform.machine(),
    }
