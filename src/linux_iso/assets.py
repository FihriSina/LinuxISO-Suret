from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlparse


ASSET_EXTENSIONS = {
    ".svg", ".svgz", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".ttf", ".otf", ".woff", ".woff2", ".wav", ".ogg",
}


def _path_pattern(home: Path) -> re.Pattern[str]:
    # Match local file references from both the source home and system/external
    # locations. HTTP(S) URLs are filtered after parsing.
    home_pat = re.escape(str(home))
    ext = r"svgz?|png|jpe?g|webp|gif|ttf|otf|woff2?|wav|ogg"
    return re.compile(
        rf"(?P<path>(?:file://)?(?:~|\$HOME|{home_pat}|/)[^\n\r\'\"]+?\.(?:{ext}))",
        re.I,
    )


def _normalize_local_reference(raw: str, home: Path) -> Path | None:
    raw = raw.strip()
    if raw.startswith(("http://", "https://")):
        return None
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        if parsed.scheme != "file":
            return None
        raw = unquote(parsed.path)
    else:
        raw = unquote(raw)
    if raw.startswith("$HOME/"):
        raw = str(home / raw[len("$HOME/") :])
    elif raw.startswith("~/"):
        raw = str(home / raw[2:])
    if raw.startswith("//"):
        return None
    candidate = Path(raw).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_file() or resolved.suffix.lower() not in ASSET_EXTENSIONS:
        return None
    return resolved


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_referenced_assets(
    configs: list[Path],
    home: Path,
    *,
    include_external: bool = False,
) -> list[Path]:
    """Return local image/font/sound files referenced by text configuration.

    By default only source-home files are returned for backwards compatibility.
    Strict-fidelity capture passes ``include_external=True`` so active wallpapers
    and other appearance assets living under /usr/share or another local path are
    snapshotted instead of being silently replaced by target-distro defaults.
    """
    found: set[Path] = set()
    home_resolved = home.resolve()
    path_re = _path_pattern(home)
    for config in configs:
        if not config.is_file() or config.stat().st_size > 8 * 1024 * 1024:
            continue
        try:
            text = config.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in path_re.finditer(text):
            resolved = _normalize_local_reference(match.group("path"), home)
            if resolved is None:
                continue
            if not include_external:
                try:
                    resolved.relative_to(home_resolved)
                except ValueError:
                    continue
            found.add(resolved)
    return sorted(found)
