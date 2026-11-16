from __future__ import annotations

import hashlib
import re
from pathlib import Path


ASSET_EXTENSIONS = {
    ".svg", ".svgz", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".ttf", ".otf", ".woff", ".woff2", ".wav", ".ogg",
}

def _path_pattern(home: Path) -> re.Pattern[str]:
    home_pat = re.escape(str(home))
    return re.compile(
        rf"(?P<path>(?:file://)?(?:~|\$HOME|{home_pat})/[^\n\r\'\"]+?\.(?:svgz?|png|jpe?g|webp|gif|ttf|otf|woff2?|wav|ogg))",
        re.I,
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_referenced_assets(configs: list[Path], home: Path) -> list[Path]:
    found: set[Path] = set()
    home_str = str(home)
    path_re = _path_pattern(home)
    for config in configs:
        if not config.is_file() or config.stat().st_size > 8 * 1024 * 1024:
            continue
        try:
            text = config.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in path_re.finditer(text):
            raw = match.group("path").replace("file://", "")
            raw = raw.replace("$HOME", home_str)
            if raw.startswith("~/"):
                raw = str(home / raw[2:])
            candidate = Path(raw).expanduser()
            try:
                resolved = candidate.resolve()
                resolved.relative_to(home.resolve())
            except (OSError, ValueError):
                continue
            if resolved.is_file() and resolved.suffix.lower() in ASSET_EXTENSIONS:
                found.add(resolved)
    return sorted(found)
