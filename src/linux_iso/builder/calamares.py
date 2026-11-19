from __future__ import annotations

import hashlib
import json
import re
import shutil
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml

from linux_iso.branding import PRODUCT_NAME
from linux_iso.installer.catalog import build_catalog, load_manifest, write_catalog


CALAMARES_JOB = r'''from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import libcalamares

CATALOG = Path("/usr/share/linux-iso/profile/catalog.json")
PENDING = Path("var/lib/linux-iso/pending-apps.json")
PAYLOAD = Path("/usr/share/linux-iso/profile/payload/home")

PERSONALIZATION_PATHS = (
    "Desktop",
    ".config/kdeglobals",
    ".config/kwinrc",
    ".config/plasmashellrc",
    ".config/plasmarc",
    ".config/plasma-org.kde.plasma.desktop-appletsrc",
    ".config/kglobalshortcutsrc",
    ".config/kwinrulesrc",
    ".config/kcminputrc",
    ".config/kscreenlockerrc",
    ".config/ksplashrc",
    ".config/krunnerrc",
    ".config/plasma-localerc",
    ".config/powermanagementprofilesrc",
    ".config/powerdevilrc",
    ".config/systemsettingsrc",
    ".config/kded6rc",
    ".config/klaunchrc",
    ".config/kactivitymanagerd-statsrc",
    ".config/breezerc",
    ".config/dolphinrc",
    ".config/konsolerc",
    ".config/mimeapps.list",
    ".config/gtk-3.0",
    ".config/gtk-4.0",
    ".config/qt5ct",
    ".config/qt6ct",
    ".config/Kvantum",
    ".local/share/plasma",
    ".local/share/aurorae",
    ".local/share/kwin",
    ".local/share/color-schemes",
    ".local/share/icons",
    ".icons",
    ".local/share/themes",
    ".themes",
    ".local/share/fonts",
    ".fonts",
    ".local/share/konsole",
    ".local/share/applications",
    ".local/share/kactivitymanagerd",
    ".face",
    ".face.icon",
)

NETINSTALL_TOKEN_PREFIX = "linuxiso__"


def _selected_ids(catalog):
    selected = set()
    # v0.3.28+ uses dynamically generated packagechooserq card pages. Each
    # category writes a comma-separated legacy GlobalStorage value. Read those
    # first; the old netinstall-token reader remains as a compatibility fallback.
    for category in catalog.get("categories", []):
        key = "packagechooser_linuxiso_" + category["id"].replace("-", "_")
        raw = libcalamares.globalstorage.value(key) or ""
        if isinstance(raw, str):
            selected.update(x.strip() for x in raw.split(",") if x.strip())
        elif isinstance(raw, (list, tuple)):
            selected.update(str(x) for x in raw if x)

    operations = libcalamares.globalstorage.value("packageOperations") or []
    if isinstance(operations, (list, tuple)):
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            for action, values in operation.items():
                if action == "source" or not isinstance(values, (list, tuple)):
                    continue
                for value in values:
                    if isinstance(value, dict):
                        value = value.get("package") or value.get("name") or ""
                    token = str(value or "")
                    if token.startswith(NETINSTALL_TOKEN_PREFIX):
                        selected.add(token[len(NETINSTALL_TOKEN_PREFIX):])
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


def _clear_vendor_personalization(target_home):
    for relative in PERSONALIZATION_PATHS:
        path = target_home / relative
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def _copy_profile(root, username):
    if not PAYLOAD.is_dir():
        raise RuntimeError("Profile payload is missing")
    target_home = root / "home" / username
    target_home.mkdir(parents=True, exist_ok=True)
    uid, gid = _target_ids(root, username)
    _clear_vendor_personalization(target_home)

    copied = 0
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
            raw = src.read_bytes()
            text = None if b"\x00" in raw else raw.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            text = None
        if text is None:
            shutil.copy2(src, dst)
        else:
            dst.write_text(text.replace("{{HOME}}", f"/home/{username}"), encoding="utf-8")
            shutil.copymode(src, dst)
        os.chown(dst, uid, gid)
        copied += 1

    marker = root / "var/lib/linux-iso/profile-applied"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"user={username}\nfiles={copied}\n", encoding="utf-8")


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


DISTRO_STYLES: dict[str, dict[str, str]] = {
    "pardus": {"accent": "#0A7BC1", "accent2": "#14A7A0", "sidebar": "#10242F", "text": "#F7FBFD"},
    "fedora": {"accent": "#3C6EB4", "accent2": "#51A2DA", "sidebar": "#1E3A5F", "text": "#FFFFFF"},
    "ubuntu": {"accent": "#E95420", "accent2": "#772953", "sidebar": "#2C001E", "text": "#FFFFFF"},
    "kubuntu": {"accent": "#0079C1", "accent2": "#31A8E0", "sidebar": "#162B3D", "text": "#FFFFFF"},
    "debian": {"accent": "#A80030", "accent2": "#D70A53", "sidebar": "#2A1820", "text": "#FFFFFF"},
    "arch": {"accent": "#1793D1", "accent2": "#33B7F0", "sidebar": "#14232C", "text": "#FFFFFF"},
    "manjaro": {"accent": "#35BF5C", "accent2": "#16A085", "sidebar": "#163026", "text": "#FFFFFF"},
    "linuxmint": {"accent": "#87CF3E", "accent2": "#5AAE2A", "sidebar": "#23321B", "text": "#FFFFFF"},
    "opensuse": {"accent": "#73BA25", "accent2": "#00B2A9", "sidebar": "#183127", "text": "#FFFFFF"},
}


def _source_identity(profile: Path) -> dict[str, str]:
    source = load_manifest(profile).get("source", {}) or {}
    distro_id = str(source.get("distro_id") or "linux").strip().lower()
    full_name = str(source.get("distro_name") or source.get("distro_name_short") or distro_id.title()).strip()
    short_name = str(source.get("distro_name_short") or distro_id.title()).strip()
    short_name = re.sub(r"\s+GNU/Linux.*$", "", short_name, flags=re.IGNORECASE).strip() or distro_id.title()
    version = str(source.get("distro_version") or "").strip()
    style = dict(DISTRO_STYLES.get(distro_id, {"accent": "#4B83C3", "accent2": "#27A6A1", "sidebar": "#18242E", "text": "#FFFFFF"}))
    return {
        "id": distro_id,
        "name": full_name,
        "short_name": short_name,
        "version": version,
        "home_url": str(source.get("distro_home_url") or ""),
        "support_url": str(source.get("distro_support_url") or ""),
        "bug_url": str(source.get("distro_bug_report_url") or ""),
        "branding_logo": str(source.get("branding_logo") or ""),
        **style,
    }


def _find_active_wallpaper(profile: Path) -> Path | None:
    config = profile / "payload/home/.config/plasma-org.kde.plasma.desktop-appletsrc"
    if not config.is_file():
        return None
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        if not raw.strip().startswith("Image="):
            continue
        value = raw.split("=", 1)[1].strip()
        if value.startswith("file:"):
            value = unquote(urlparse(value).path)
        if value.startswith("{{HOME}}/"):
            candidate = profile / "payload/home" / value[len("{{HOME}}/") :]
        elif value.startswith("/home/"):
            parts = Path(value).parts
            candidate = profile / "payload/home" / Path(*parts[3:]) if len(parts) > 3 else None
        else:
            candidate = profile / "payload/home" / value.lstrip("/")
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def _write_fallback_logo(path: Path, identity: dict[str, str]) -> None:
    initials = "".join(part[:1] for part in identity["short_name"].split()[:2]).upper() or "S"
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">\n'''
        f'''<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{identity['accent']}"/><stop offset="1" stop-color="{identity['accent2']}"/></linearGradient></defs>\n'''
        '''<rect width="256" height="256" rx="56" fill="url(#g)"/>\n'''
        f'''<text x="128" y="154" text-anchor="middle" font-family="sans-serif" font-size="92" font-weight="700" fill="white">{escape(initials)}</text>\n'''
        '''</svg>\n''',
        encoding="utf-8",
    )


def _write_source_branding(profile: Path, root: Path) -> dict[str, str]:
    identity = _source_identity(profile)
    branding = root / "etc/calamares/branding/linuxiso-source"
    branding.mkdir(parents=True, exist_ok=True)

    logo_name = "source-logo.svg"
    logo_source = profile / identity["branding_logo"] if identity.get("branding_logo") else None
    if logo_source is not None and logo_source.is_file():
        logo_name = "source-logo" + (logo_source.suffix.lower() or ".img")
        shutil.copy2(logo_source, branding / logo_name)
    else:
        _write_fallback_logo(branding / logo_name, identity)

    wallpaper_name = ""
    wallpaper = _find_active_wallpaper(profile)
    if wallpaper is not None:
        wallpaper_name = "source-wallpaper" + wallpaper.suffix.lower()
        shutil.copy2(wallpaper, branding / wallpaper_name)

    (branding / "banner.svg").write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="150" viewBox="0 0 900 150">\n'''
        f'''<rect width="900" height="150" rx="24" fill="{identity['sidebar']}"/>\n'''
        f'''<circle cx="76" cy="75" r="46" fill="{identity['accent']}"/>\n'''
        f'''<text x="145" y="72" font-family="sans-serif" font-size="40" font-weight="700" fill="white">{escape(identity['short_name'])}</text>\n'''
        f'''<text x="145" y="110" font-family="sans-serif" font-size="21" fill="#DCEAF2">Kaynak masaustu profili • Suret kurulumu</text>\n'''
        '''</svg>\n''',
        encoding="utf-8",
    )

    desc = {
        "componentName": "linuxiso-source",
        "welcomeStyleCalamares": False,
        "welcomeExpandingLogo": True,
        "windowExpanding": "normal",
        "windowSize": "1180px,760px",
        "windowPlacement": "center",
        "sidebar": "widget",
        "navigation": "widget",
        "strings": {
            "productName": identity["short_name"],
            "shortProductName": identity["short_name"],
            "version": identity["version"],
            "shortVersion": identity["version"],
            "versionedName": identity["name"],
            "shortVersionedName": identity["short_name"] + ((" " + identity["version"]) if identity["version"] else ""),
            "bootloaderEntryName": identity["short_name"],
            "productUrl": identity["home_url"],
            "supportUrl": identity["support_url"],
            "knownIssuesUrl": identity["bug_url"],
            "releaseNotesUrl": "",
            "donateUrl": "",
        },
        "images": {
            "productBanner": "banner.svg",
            "productIcon": logo_name,
            "productLogo": logo_name,
            "productWelcome": "banner.svg",
        },
        "style": {
            "SidebarBackground": identity["sidebar"],
            "SidebarText": identity["text"],
            "SidebarTextCurrent": "#FFFFFF",
            "SidebarBackgroundCurrent": identity["accent"],
        },
        "slideshow": "show.qml",
        "slideshowAPI": 2,
        "uploadServer": {"type": "none", "url": "", "sizeLimit": -1},
    }
    (branding / "branding.desc").write_text(yaml.safe_dump(desc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (branding / "stylesheet.qss").write_text(
        f'''#sidebarApp {{ background: {identity['sidebar']}; color: {identity['text']}; }}\n'''
        f'''QPushButton {{ min-height: 32px; border-radius: 7px; padding: 4px 12px; }}\n'''
        f'''QPushButton:default {{ background: {identity['accent']}; color: white; border: none; }}\n''',
        encoding="utf-8",
    )
    wallpaper_source = f'"{wallpaper_name}"' if wallpaper_name else '""'
    qml_name = identity["name"].replace('"', '\\"')
    qml_short = identity["short_name"].replace('"', '\\"')
    (branding / "show.qml").write_text(
        f'''import QtQuick 2.15\nimport calamares.slideshow 1.0\nPresentation {{\n'''
        '''    id: presentation\n    Timer { interval: 5500; running: presentation.activatedInCalamares; repeat: true; onTriggered: presentation.goToNextSlide() }\n'''
        '''    Slide {\n        Rectangle { anchors.fill: parent; color: "#101820"\n'''
        f'''            Image {{ anchors.fill: parent; source: {wallpaper_source}; fillMode: Image.PreserveAspectCrop; visible: source.toString().length > 0; opacity: 0.64 }}\n'''
        '''            Rectangle { anchors.fill: parent; color: "#70000000" }\n'''
        f'''            Text {{ anchors.centerIn: parent; text: "{qml_name}\\nKuruluyor"; color: "white"; font.pixelSize: 34; font.bold: true; horizontalAlignment: Text.AlignHCenter }}\n'''
        '''        }\n    }\n'''
        f'''    Slide {{ centeredText: "{qml_short} masaustu ayarlari, tema, simgeler ve kullanici tercihleri geri yukleniyor." }}\n'''
        '''    function onActivate() { presentation.currentSlide = 0 }\n    function onLeave() {}\n}\n''',
        encoding="utf-8",
    )
    return identity


def _captured_app_icon(profile: Path, item: dict[str, Any]) -> Path | None:
    payload = profile / "payload/home"
    app_dirs = (payload / ".local/share/applications", payload / "Desktop")
    package_name = str(item.get("name") or "")
    display_name = str(item.get("display_name") or package_name)
    tokens = {
        package_name.lower(),
        package_name.rsplit(".", 1)[-1].lower(),
        display_name.lower(),
        display_name.lower().replace(" ", "-"),
    }
    icon_names: list[str] = []
    for app_dir in app_dirs:
        if not app_dir.is_dir():
            continue
        for desktop in app_dir.glob("*.desktop"):
            try:
                text = desktop.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            haystack = (desktop.stem + "\n" + text).lower()
            if not any(token and token in haystack for token in tokens):
                continue
            for line in text.splitlines():
                if line.startswith("Icon="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        icon_names.append(value)
                    break
    for value in icon_names:
        if value.startswith("{{HOME}}/"):
            candidate = payload / value[len("{{HOME}}/") :]
            if candidate.is_file():
                return candidate
        path = Path(value)
        if path.is_absolute():
            # Absolute source-home paths are rewritten during capture; absolute
            # system icons are intentionally not trusted here.
            continue
        for base in (payload / ".local/share/icons", payload / ".icons", payload / ".local/share/pixmaps"):
            if not base.is_dir():
                continue
            for suffix in (".svg", ".svgz", ".png", ".xpm"):
                matches = list(base.rglob(value + suffix))
                if matches:
                    return matches[0]
    # Last chance: captured icons whose basename resembles the package/app.
    normalized = {re.sub(r"[^a-z0-9]+", "", token) for token in tokens if token}
    for base in (payload / ".local/share/icons", payload / ".icons"):
        if not base.is_dir():
            continue
        for candidate in base.rglob("*"):
            if not candidate.is_file() or candidate.suffix.lower() not in {".svg", ".svgz", ".png", ".xpm"}:
                continue
            stem = re.sub(r"[^a-z0-9]+", "", candidate.stem.lower())
            if stem and any(token and (stem == token or stem in token or token in stem) for token in normalized):
                return candidate
    return None


def _app_cover_svg(item: dict[str, Any], identity: dict[str, str]) -> str:
    display = str(item.get("display_name") or item["name"])
    initials = "".join(part[:1] for part in re.split(r"[ ._+-]+", display) if part)[:2].upper() or "APP"
    digest = hashlib.blake2s(str(item["id"]).encode("utf-8"), digest_size=3).hexdigest()
    tint = "#" + digest
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="210" viewBox="0 0 360 210">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{identity["accent"]}"/><stop offset="1" stop-color="{tint}"/></linearGradient></defs>'
        '<rect width="360" height="210" rx="28" fill="url(#g)"/>'
        '<circle cx="180" cy="92" r="55" fill="#22FFFFFF" stroke="#55FFFFFF" stroke-width="2"/>'
        f'<text x="180" y="110" text-anchor="middle" font-family="sans-serif" font-size="50" font-weight="700" fill="white">{escape(initials)}</text>'
        f'<text x="180" y="177" text-anchor="middle" font-family="sans-serif" font-size="20" font-weight="600" fill="white">{escape(display[:28])}</text>'
        '</svg>'
    )


def _category_qml(profile: Path, category: dict[str, Any], identity: dict[str, str], cards_dir: Path) -> str:
    apps = []
    selected = {}
    for item in category["items"]:
        captured_icon = _captured_app_icon(profile, item)
        if captured_icon is not None:
            card = cards_dir / f"{item['id']}-icon{captured_icon.suffix.lower()}"
            shutil.copy2(captured_icon, card)
            image_kind = "icon"
        else:
            card = cards_dir / f"{item['id']}.svg"
            card.write_text(_app_cover_svg(item, identity), encoding="utf-8")
            image_kind = "cover"
        apps.append({
            "id": item["id"],
            "name": item.get("display_name") or item["name"],
            "description": item.get("description") or "Optional application",
            "provider": str(item.get("provider") or "").upper(),
            "image": "file:///etc/calamares/linuxiso-app-cards/" + card.name,
            "imageKind": image_kind,
        })
        selected[item["id"]] = True
    apps_json = json.dumps(apps, ensure_ascii=False)
    selected_json = json.dumps(selected, ensure_ascii=False)
    accent = identity["accent"]
    return f'''import QtQuick 2.15\nimport QtQuick.Controls 2.15\nimport QtQuick.Layouts 1.15\n\nItem {{\n    id: root\n    width: parent ? parent.width : 960\n    height: parent ? parent.height : 640\n    property var apps: {apps_json}\n    property var selections: {selected_json}\n    function syncChoice() {{\n        var ids = [];\n        for (var i = 0; i < apps.length; ++i) {{\n            if (selections[apps[i].id]) ids.push(apps[i].id);\n        }}\n        config.packageChoice = ids.join(",");\n    }}\n    function updateChoice(id, checked) {{ selections[id] = checked; syncChoice(); }}\n    Component.onCompleted: syncChoice()\n\n    ColumnLayout {{\n        anchors.fill: parent\n        anchors.margins: 18\n        spacing: 12\n        Label {{ text: "{category['label']}"; font.pixelSize: 28; font.bold: true; Layout.fillWidth: true }}\n        Label {{ text: "Tum uygulamalar secili baslar. Istemediklerinizin isaretini kaldirin."; opacity: 0.72; wrapMode: Text.WordWrap; Layout.fillWidth: true }}\n        ScrollView {{\n            Layout.fillWidth: true\n            Layout.fillHeight: true\n            clip: true\n            GridLayout {{\n                width: Math.max(280, root.width - 50)\n                columns: Math.max(1, Math.floor(width / 285))\n                rowSpacing: 14\n                columnSpacing: 14\n                Repeater {{\n                    model: root.apps\n                    delegate: Frame {{\n                        Layout.preferredWidth: 270\n                        Layout.preferredHeight: 290\n                        padding: 10\n                        background: Rectangle {{ color: "#171D23"; border.color: check.checked ? "{accent}" : "#3B4652"; border.width: check.checked ? 2 : 1; radius: 14 }}\n                        ColumnLayout {{\n                            anchors.fill: parent\n                            spacing: 8\n                            Image {{ source: modelData.image; Layout.fillWidth: true; Layout.preferredHeight: 145; fillMode: Image.PreserveAspectFit; asynchronous: true; cache: true }}\n                            RowLayout {{\n                                Layout.fillWidth: true\n                                Label {{ text: modelData.name; color: "#FFFFFF"; font.pixelSize: 17; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }}\n                                Label {{ text: modelData.provider; color: "#AAB4BE"; font.pixelSize: 10; opacity: 0.85 }}\n                            }}\n                            Label {{ text: modelData.description; color: "#CBD3DA"; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight; opacity: 0.95; Layout.fillWidth: true; Layout.fillHeight: true }}\n                            CheckBox {{ id: check; text: "Kur"; checked: true; palette.text: "#FFFFFF"; onToggled: root.updateChoice(modelData.id, checked) }}\n                        }}\n                    }}\n                }}\n            }}\n        }}\n    }}\n}}\n'''


def _category_conf(category: dict[str, Any], qml_path: Path) -> dict[str, Any]:
    return {
        "method": "legacy",
        "labels": {"step": f"Applications - {category['label']}"},
        "packageChoice": ",".join(item["id"] for item in category["items"]),
        "qmlSearch": "both",
        "qmlFilename": str(qml_path),
    }

def generate_calamares_overlay(profile: Path, root: Path) -> dict[str, Any]:
    # Write source-branded Linux ISO Calamares integration into a KIWI overlay root.
    catalog = build_catalog(profile)
    identity = _write_source_branding(profile, root)
    share_profile = root / "usr/share/linux-iso/profile"
    share_profile.mkdir(parents=True, exist_ok=True)
    write_catalog(profile, share_profile / "catalog.json")

    modules_dir = root / "etc/calamares/modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    qml_dir = root / "etc/calamares/linuxiso-app-qml"
    cards_dir = root / "etc/calamares/linuxiso-app-cards"
    qml_dir.mkdir(parents=True, exist_ok=True)
    cards_dir.mkdir(parents=True, exist_ok=True)
    instances = []
    show = []

    for category in catalog["categories"]:
        instance_id = "linuxiso_" + category["id"].replace("-", "_")
        qml_path = qml_dir / f"{instance_id}.qml"
        qml_path.write_text(_category_qml(profile, category, identity, cards_dir), encoding="utf-8")
        conf_name = f"packagechooserq-{instance_id}.conf"
        (modules_dir / conf_name).write_text(
            yaml.safe_dump(_category_conf(category, Path("/etc/calamares/linuxiso-app-qml") / qml_path.name), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        instances.append({"id": instance_id, "module": "packagechooserq", "config": conf_name})
        show.append(f"packagechooserq@{instance_id}")

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
        "source_product": identity["name"],
        "branding": "linuxiso-source",
        "instances": instances,
        "sequence_patch": {
            "insert_before_summary": show,
            "insert_in_exec_after_users": ["linuxiso-install"],
        },
        "globalstorage_keys": [
            "packagechooser_linuxiso_" + category["id"].replace("-", "_")
            for category in catalog["categories"]
        ],
        "notes": [
            "Merge this fragment into the distro's Calamares settings.conf.",
            "The installer branding is generated from the captured source distribution identity.",
            "Optional applications are shown as dynamically generated visual cards, never a static shared QML page.",
            "Every optional application starts selected; users opt out by unchecking it.",
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

