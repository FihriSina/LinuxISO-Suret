from __future__ import annotations

import shutil
from pathlib import Path

import yaml


class RestoreError(RuntimeError):
    pass


def restore_profile(profile: Path, target_home: Path, apply: bool = False) -> list[tuple[Path, Path]]:
    profile = profile.expanduser().resolve()
    target_home = target_home.expanduser().resolve()
    manifest_path = profile / "manifest.yaml"
    payload = profile / "payload/home"
    if not manifest_path.is_file() or not payload.is_dir():
        raise RestoreError("Profile is missing manifest.yaml or payload/home.")

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    placeholder = manifest.get("restore", {}).get("home_placeholder", "{{HOME}}")
    operations: list[tuple[Path, Path]] = []

    for src in payload.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(payload)
        dst = target_home / rel
        operations.append((src, dst))
        if not apply:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = src.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            shutil.copy2(src, dst)
        else:
            dst.write_text(text.replace(placeholder, str(target_home)), encoding="utf-8")
            shutil.copymode(src, dst)

    return operations
