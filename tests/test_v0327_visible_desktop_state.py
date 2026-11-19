from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from linux_iso.capture import capture_profile
from linux_iso.verification import verify_profile


def _patch_capture(monkeypatch):
    import linux_iso.capture as capture

    monkeypatch.setattr(capture, "detect_desktop", lambda: ("kde-plasma", "6.test"))
    monkeypatch.setattr(
        capture,
        "collect_system_info",
        lambda: {"distro_id": "pardus", "distro_name": "Pardus Test", "architecture": "x86_64"},
    )
    monkeypatch.setattr(capture, "collect_packages", lambda: [])
    monkeypatch.setattr(capture, "referenced_widgets", lambda _home: [])
    monkeypatch.setattr(capture, "user_plasmoids", lambda _home: [])
    monkeypatch.setattr(capture, "active_kwin_user_components", lambda _home: [])
    monkeypatch.setattr(capture, "active_kde_components", lambda _home: [])
    monkeypatch.setattr(capture, "icon_theme_inheritance_chain", lambda _home, _name: [])


def test_v0327_captures_kickoff_favorites_order_membership_and_avatar(tmp_path: Path, monkeypatch):
    _patch_capture(monkeypatch)
    home = tmp_path / "home"
    config = home / ".config"
    apps = home / ".local/share/applications"
    resources = home / ".local/share/kactivitymanagerd/resources"
    config.mkdir(parents=True)
    apps.mkdir(parents=True)
    resources.mkdir(parents=True)

    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1]\nplugin=org.kde.plasma.folder\n",
        encoding="utf-8",
    )
    (config / "kactivitymanagerd-statsrc").write_text(
        "[Favorites-org.kde.plasma.kickoff.favorites.instance-7-global]\n"
        "ordering=applications:alpha.desktop,applications:beta.desktop\n\n"
        "[Usage-org.kde.plasma.kickoff]\nlastUsed=secret-history\n",
        encoding="utf-8",
    )
    for app in ("alpha", "beta"):
        (apps / f"{app}.desktop").write_text(
            f"[Desktop Entry]\nType=Application\nName={app.title()}\nExec={app}\nIcon={app}\n",
            encoding="utf-8",
        )
    (home / ".face").write_bytes(b"avatar-bytes")

    db = resources / "database"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE SchemaInfo(key TEXT, value TEXT)")
    conn.execute("CREATE TABLE ResourceLink(usedActivity TEXT, initiatingAgent TEXT, targettedResource TEXT)")
    conn.execute("CREATE TABLE ResourceEvent(resource TEXT)")
    conn.execute("INSERT INTO SchemaInfo VALUES('version', '2015.02.09')")
    conn.execute(
        "INSERT INTO ResourceLink VALUES(':global', 'org.kde.plasma.favorites.applications', 'applications:alpha.desktop')"
    )
    conn.execute(
        "INSERT INTO ResourceLink VALUES(':global', 'org.kde.plasma.favorites.applications', 'applications:beta.desktop')"
    )
    conn.execute(
        "INSERT INTO ResourceLink VALUES(':global', 'org.kde.plasma.favorites.documents', '/home/sina/private.txt')"
    )
    conn.execute("INSERT INTO ResourceEvent VALUES('/home/sina/private-history.txt')")
    conn.commit()
    conn.close()

    profile = tmp_path / "profile"
    manifest = capture_profile(profile, home)

    assert manifest.restore["fidelity_schema"] == 6
    assert (profile / "payload/home/.face").read_bytes() == b"avatar-bytes"
    assert (profile / "payload/home/.local/share/applications/alpha.desktop").is_file()
    assert (profile / "payload/home/.local/share/applications/beta.desktop").is_file()

    stats = (profile / "payload/home/.config/kactivitymanagerd-statsrc").read_text(
        encoding="utf-8"
    )
    assert "ordering=applications:alpha.desktop,applications:beta.desktop" in stats
    assert "Usage-org.kde.plasma.kickoff" not in stats
    assert "secret-history" not in stats

    target_db = profile / "payload/home/.local/share/kactivitymanagerd/resources/database"
    out = sqlite3.connect(target_db)
    rows = out.execute(
        "SELECT initiatingAgent, targettedResource FROM ResourceLink ORDER BY rowid"
    ).fetchall()
    events = out.execute("SELECT * FROM ResourceEvent").fetchall()
    schema = out.execute("SELECT * FROM SchemaInfo").fetchall()
    out.close()
    assert rows == [
        ("org.kde.plasma.favorites.applications", "applications:alpha.desktop"),
        ("org.kde.plasma.favorites.applications", "applications:beta.desktop"),
    ]
    assert events == []
    assert schema == [("version", "2015.02.09")]
    assert verify_profile(profile).ok


def test_v0327_slideshow_uses_most_recent_source_slide_as_initial_image(tmp_path: Path, monkeypatch):
    _patch_capture(monkeypatch)
    home = tmp_path / "home"
    config = home / ".config"
    slides = home / "Resimler/ArkaPlanlar"
    config.mkdir(parents=True)
    slides.mkdir(parents=True)

    old = slides / "old.jpg"
    whale = slides / "dreamlike-whale.jpg"
    old.write_bytes(b"old")
    whale.write_bytes(b"whale")
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    os.utime(whale, ns=(9_000_000_000, 2_000_000_000))

    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1][Wallpaper][org.kde.slideshow][General]\n"
        "Image=file:///usr/share/wallpapers/Next/contents/images/1920x1080.png\n"
        f"SlidePaths=file://{slides}\n",
        encoding="utf-8",
    )

    profile = tmp_path / "profile"
    capture_profile(profile, home)
    restored = (
        profile / "payload/home/.config/plasma-org.kde.plasma.desktop-appletsrc"
    ).read_text(encoding="utf-8")

    assert "Image=file://{{HOME}}/Resimler/ArkaPlanlar/dreamlike-whale.jpg" in restored
    assert "[Wallpaper][org.kde.image][General]" in restored
    assert "[Wallpaper][org.kde.slideshow][General]" not in restored
    assert (profile / "payload/home/Resimler/ArkaPlanlar/dreamlike-whale.jpg").is_file()
    assert verify_profile(profile).ok


def test_v0327_calamares_checkbox_jobs_run_before_mixed_provider_installer(tmp_path: Path):
    import yaml
    from linux_iso.builder.kiwi import generate_kiwi_project

    profile = tmp_path / "installer-profile"
    (profile / "payload/home/.config").mkdir(parents=True)
    (profile / "payload/home/.config/kdeglobals").write_text("[General]\n", encoding="utf-8")
    (profile / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source": {"distro_id": "pardus", "architecture": "x86_64"},
                "desktop": {"desktop": "kde-plasma", "configs": [], "custom_assets": []},
                "packages": [
                    {
                        "name": "firefox",
                        "provider": "apt",
                        "category": "internet",
                        "required_for_appearance": False,
                        "installer_visible": True,
                    },
                    {
                        "name": "org.signal.Signal",
                        "provider": "flatpak",
                        "category": "communication",
                        "required_for_appearance": False,
                        "installer_visible": True,
                    },
                ],
                "security": {"safe_mode": True},
                "restore": {"home_placeholder": "{{HOME}}", "payload_root": "payload/home"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    build = tmp_path / "build"
    generate_kiwi_project(profile, build)

    settings = tmp_path / "settings.conf"
    settings.write_text(
        yaml.safe_dump(
            {
                "modules-search": ["local"],
                "instances": [],
                "sequence": [
                    {"show": ["welcome", "users", "summary"]},
                    {"exec": ["mount", "users", "displaymanager", "umount"]},
                    {"show": ["finished"]},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    fragment = build / "root/etc/calamares/linux-iso-settings-fragment.yaml"
    merge_script = (build / "root/usr/lib/linux-iso/patch-calamares.py").read_text(encoding="utf-8")
    merge_ns = {"__name__": "merge_test"}
    exec(compile(merge_script, "patch-calamares.py", "exec"), merge_ns)
    merge_ns["SETTINGS"] = settings
    merge_ns["FRAGMENT"] = fragment
    merge_ns["main"]()

    merged = yaml.safe_load(settings.read_text(encoding="utf-8"))
    show = merged["sequence"][0]["show"]
    jobs = merged["sequence"][1]["exec"]
    selectors = [item for item in show if item.startswith("packagechooserq@linuxiso_")]
    assert selectors == ["packagechooserq@linuxiso_internet", "packagechooserq@linuxiso_communication"]
    assert all(selector not in jobs for selector in selectors)
    assert jobs.index("users") < jobs.index("linuxiso-install")
    assert merged["branding"] == "linuxiso-source"

    runtime_script = (build / "root/usr/lib/linux-iso/patch-calamares-runtime.py").read_text(
        encoding="utf-8"
    )
    runtime_ns = {"__name__": "runtime_test"}
    exec(compile(runtime_script, "patch-calamares-runtime.py", "exec"), runtime_ns)
    runtime_ns["SETTINGS"] = settings
    runtime_ns["MODULES"] = tmp_path / "modules"
    runtime_ns["MODULES"].mkdir()
    runtime_ns["patch_settings"]()

    patched = yaml.safe_load(settings.read_text(encoding="utf-8"))["sequence"][1]["exec"]
    profile_job = "shellprocess@linuxiso_apply_target_profile"
    assert patched.index("users") < patched.index(profile_job)
    assert patched.index(profile_job) < patched.index("linuxiso-install")
    assert all(selector not in patched for selector in selectors)
