from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Package:
    name: str
    provider: str
    category: str = "other"
    required_for_appearance: bool = False
    reason: str | None = None


@dataclass
class CapturedFile:
    source: str
    destination: str
    kind: str
    sha256: str | None = None
    rewritten_home_paths: int = 0
    sanitized_lines: int = 0


@dataclass
class DesktopProfile:
    desktop: str
    version: str | None = None
    configs: list[CapturedFile] = field(default_factory=list)
    custom_assets: list[CapturedFile] = field(default_factory=list)
    widgets: list[str] = field(default_factory=list)
    user_plasmoids: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    schema_version: int
    created_at: str
    source: dict[str, Any]
    desktop: DesktopProfile
    packages: list[Package]
    security: dict[str, Any]
    restore: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
