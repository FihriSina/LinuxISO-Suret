from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from linux_iso.branding import PRODUCT_NAME
from linux_iso.installer.catalog import build_catalog, write_catalog


CALAMARES_JOB = r'''from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import libcalamares

CATALOG = Path("/usr/share/linux-iso/profile/catalog.json")
PENDING = Path("var/lib/linux-iso/pending-apps.json")
PAYLOAD = Path("/usr/share/linux-iso/profile/payload/home")


def _selected_ids(catalog):
    selected = set()
    for category in catalog.get("categories", []):
        key = "packagechooser_linuxiso_" + category["id"].replace("-", "_")
        raw = libcalamares.globalstorage.value(key) or ""
        if isinstance(raw, str):
            selected.update(x.strip() for x in raw.split(",") if x.strip())
        elif isinstance(raw, (list, tuple)):
            selected.update(str(x) for x in raw if x)
    return selected


def _collect(catalog, selected_ids):
    chosen = list(catalog.get("required_for_appearance", []))
    for category in catalog.get("categories", []):
        for item in category.get("items", []):
            if item.get("id") in selected_ids:
                chosen.append(item)

    # Keep stable order while de-duplicating provider/name pairs.
    seen = set()
    result = []
    for item in chosen:
        key = (item.get("provider"), item.get("name"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _target_ids(root, username):
    passwd = root / "etc/passwd"
    for line in passwd.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split(":")
        if len(fields) >= 4 and fields[0] == username:
            return int(fields[2]), int(fields[3])
    raise RuntimeError("Could not resolve target user UID/GID")


def _copy_profile(root, username):
    if not PAYLOAD.is_dir():
        raise RuntimeError("Profile payload is missing")
    target_home = root / "home" / username
    target_home.mkdir(parents=True, exist_ok=True)
    uid, gid = _target_ids(root, username)

    for src in PAYLOAD.rglob("*"):
        rel = src.relative_to(PAYLOAD)
        dst = target_home / rel
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
            dst.write_text(text.replace("{{HOME}}", f"/home/{username}"), encoding="utf-8")
            shutil.copymode(src, dst)
        os.chown(dst, uid, gid)


def _target_call(command):
    try:
        return libcalamares.utils.target_env_call(command) == 0
    except Exception:
        return False


def _install_apt(items):
    if not items:
        return []
    names = [item["name"] for item in items]
    if _target_call(["apt-get", "update"]) and _target_call(
        ["apt-get", "install", "-y", *names]
    ):
        return []
    return items


def _install_flatpak(items):
    pending = []
    for item in items:
        remote = item.get("source") or "flathub"
        remote_url = item.get("source_url")
        if remote_url:
            if not _target_call(
                ["flatpak", "remote-add", "--system", "--if-not-exists", remote, remote_url]
            ):
                pending.append(item)
                continue
        if not _target_call(["flatpak", "install", "--system", "-y", remote, item["name"]]):
            pending.append(item)
    return pending


def _install_online(items):
    apt = [x for x in items if x.get("provider") == "apt"]
    flatpak = [x for x in items if x.get("provider") == "flatpak"]
    # snapd is not reliable inside an installer chroot because its daemon is not running.
    pending = [x for x in items if x.get("provider") not in {"apt", "flatpak"}]
    pending.extend(_install_apt(apt))
    pending.extend(_install_flatpak(flatpak))
    return pending


def _write_pending(root, pending):
    path = root / PENDING
    if pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"selected": pending}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        path.unlink(missing_ok=True)


def run():
    try:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        selected = _selected_ids(catalog)
        chosen = _collect(catalog, selected)
        root = Path(libcalamares.globalstorage.value("rootMountPoint") or "/")
        username = libcalamares.globalstorage.value("username")
        if not username:
            raise RuntimeError("Calamares username is not available")

        marker = root / "var/lib/linux-iso/target-username"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(username) + "\n", encoding="utf-8")

        # Appearance/configuration is always applied. Optional applications are user-selected.
        _copy_profile(root, username)
        pending = _install_online(chosen)
        _write_pending(root, pending)
        return None
    except Exception as exc:
        return ("Linux ISO profile application failed", str(exc))
'''

FIRSTBOOT_SCRIPT = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PENDING = Path("/var/lib/linux-iso/pending-apps.json")
DONE = Path("/var/lib/linux-iso/apps-installed")


def run(cmd):
    proc = subprocess.run(cmd, check=False)
    return proc.returncode == 0


def install_apt(items):
    if not items:
        return []
    if shutil.which("apt-get") is None:
        return items
    names = [item["name"] for item in items]
    if run(["apt-get", "update"]) and run(["apt-get", "install", "-y", *names]):
        return []
    return items


def install_flatpak(items):
    if not items:
        return []
    if shutil.which("flatpak") is None:
        return items
    pending = []
    for item in items:
        remote = item.get("source") or "flathub"
        remote_url = item.get("source_url")
        if remote_url and not run(
            ["flatpak", "remote-add", "--system", "--if-not-exists", remote, remote_url]
        ):
            pending.append(item)
            continue
        if not run(["flatpak", "install", "--system", "-y", remote, item["name"]]):
            pending.append(item)
    return pending


def install_snap(items):
    if not items:
        return []
    if shutil.which("snap") is None:
        return items
    pending = []
    for item in items:
        cmd = ["snap", "install", item["name"]]
        cmd.extend(item.get("install_options") or [])
        channel = item.get("source")
        if channel and channel != "latest/stable":
            cmd.extend(["--channel", channel])
        if not run(cmd):
            pending.append(item)
    return pending


def main():
    if DONE.exists() or not PENDING.exists():
        return 0

    data = json.loads(PENDING.read_text(encoding="utf-8"))
    selected = data.get("selected", [])
    apt = [x for x in selected if x.get("provider") == "apt"]
    flatpak = [x for x in selected if x.get("provider") == "flatpak"]
    snap = [x for x in selected if x.get("provider") == "snap"]
    unknown = [x for x in selected if x.get("provider") not in {"apt", "flatpak", "snap"}]

    pending = []
    pending.extend(install_apt(apt))
    pending.extend(install_flatpak(flatpak))
    pending.extend(install_snap(snap))
    pending.extend(unknown)

    if pending:
        PENDING.write_text(
            json.dumps({"selected": pending}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 1

    DONE.parent.mkdir(parents=True, exist_ok=True)
    DONE.write_text("ok\n", encoding="utf-8")
    PENDING.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

FIRSTBOOT_SERVICE = '''[Unit]
Description=Linux ISO online application installation fallback
ConditionPathExists=/var/lib/linux-iso/pending-apps.json
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/lib/linux-iso/firstboot.py

[Install]
WantedBy=multi-user.target
'''


def _category_conf(category: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "optionalmultiple",
        "method": "legacy",
        "labels": {"step": f"Applications - {category['label']}"},
        "items": [
            {
                "id": item["id"],
                "name": item["name"],
                "description": (
                    f"Install online with {item['provider']} during installation "
                    "(with first-boot fallback if needed)."
                ),
                "screenshot": ":/images/no-selection.png",
            }
            for item in category["items"]
        ],
    }


def generate_calamares_overlay(profile: Path, root: Path) -> dict[str, Any]:
    """Write Linux ISO Calamares integration into a KIWI overlay root."""
    catalog = build_catalog(profile)
    share_profile = root / "usr/share/linux-iso/profile"
    share_profile.mkdir(parents=True, exist_ok=True)
    write_catalog(profile, share_profile / "catalog.json")

    modules_dir = root / "etc/calamares/modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    instances = []
    show = []

    for category in catalog["categories"]:
        instance_id = "linuxiso_" + category["id"].replace("-", "_")
        conf_name = f"packagechooser-{instance_id}.conf"
        (modules_dir / conf_name).write_text(
            yaml.safe_dump(_category_conf(category), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        instances.append({"id": instance_id, "module": "packagechooser", "config": conf_name})
        show.append(f"packagechooser@{instance_id}")

    job_dir = root / "usr/share/linux-iso/calamares/modules/linuxiso-install"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "module.desc").write_text(
        "name: linuxiso-install\ntype: job\ninterface: python\nscript: main.py\nnoconfig: true\n",
        encoding="utf-8",
    )
    (job_dir / "main.py").write_text(CALAMARES_JOB, encoding="utf-8")

    helper = root / "usr/lib/linux-iso/firstboot.py"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(FIRSTBOOT_SCRIPT, encoding="utf-8")
    helper.chmod(0o755)

    systemd = root / "etc/systemd/system"
    systemd.mkdir(parents=True, exist_ok=True)
    (systemd / "linux-iso-firstboot.service").write_text(FIRSTBOOT_SERVICE, encoding="utf-8")
    wants = systemd / "multi-user.target.wants"
    wants.mkdir(parents=True, exist_ok=True)
    link = wants / "linux-iso-firstboot.service"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to("../linux-iso-firstboot.service")

    integration = {
        "product": PRODUCT_NAME,
        "instances": instances,
        "sequence_patch": {
            "insert_before_summary": show,
            "insert_in_exec_after_users": ["linuxiso-install"],
        },
        "globalstorage_keys": ["packagechooser_" + i["id"] for i in instances],
        "notes": [
            "Merge this fragment into the distro's Calamares settings.conf.",
            "Optional applications are selected category-by-category in packagechooser pages.",
            "APT/Flatpak selections are installed in the target during Calamares when possible.",
            "Snap, unsupported providers, or failed online installs are retried by linux-iso-firstboot.",
            "Appearance-required items are not optional and are always included in the install plan.",
        ],
    }
    (root / "etc/calamares/linux-iso-settings-fragment.yaml").write_text(
        yaml.safe_dump(integration, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return integration
