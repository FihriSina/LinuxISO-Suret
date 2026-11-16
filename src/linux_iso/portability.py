from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from linux_iso.branding import PRODUCT_NAME
from linux_iso.verification import verify_profile


@dataclass
class PortabilityResult:
    ready: bool
    target_recipe: str
    checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.ready:
            status = "BLOCKED"
        elif self.warnings:
            status = "READY WITH WARNINGS"
        else:
            status = "READY"
        lines = [
            f"{PRODUCT_NAME} portability report",
            "=" * 36,
            f"Status: {status}",
            f"Target recipe: {self.target_recipe}",
            "",
            "Checks",
            "------",
        ]
        lines.extend(f"- {item}" for item in self.checks) if self.checks else lines.append("(none)")
        lines.extend(["", "Warnings", "--------"])
        lines.extend(f"- {item}" for item in self.warnings) if self.warnings else lines.append("(none)")
        lines.extend(["", "Blockers", "--------"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("(none)")
        return "\n".join(lines)


def _manifest(profile: Path) -> dict[str, Any]:
    path = profile / "manifest.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _version_tuple(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    parts = []
    for token in str(value).split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def portability_report(profile: Path, recipe_id: str = "ubuntu-26.04-kde") -> PortabilityResult:
    # Lazy import avoids coupling profile capture/verification to the image builder.
    from linux_iso.builder.kiwi import RECIPES

    profile = profile.expanduser().resolve()
    manifest = _manifest(profile)
    if recipe_id not in RECIPES:
        raise KeyError(f"Unknown recipe: {recipe_id}")
    recipe = RECIPES[recipe_id]
    verification = verify_profile(profile)

    checks: list[str] = []
    warnings: list[str] = list(verification.warnings)
    blockers: list[str] = list(verification.errors)

    source = manifest.get("source", {})
    distro = source.get("distro_name") or source.get("distro_id") or "unknown"
    arch = source.get("architecture") or "unknown"
    checks.append(f"Source system: {distro} ({arch})")
    if recipe.target_plasma_version:
        checks.append(f"Target Plasma: {recipe.target_plasma_version}")
    checks.append(
        "Profile verification: "
        + ("PASS WITH WARNINGS" if verification.ok and verification.warnings else "PASS" if verification.ok else "FAIL")
    )

    packages = manifest.get("packages", [])
    native = sorted(
        {
            str(item.get("provider"))
            for item in packages
            if item.get("provider") in {"apt", "pacman", "dnf", "zypper"}
        }
    )
    incompatible = [provider for provider in native if provider != recipe.native_provider]
    if incompatible:
        blockers.append(
            f"Target recipe uses {recipe.native_provider}, but profile has native package provider(s): "
            + ", ".join(incompatible)
        )
    else:
        provider_text = ", ".join(native) if native else "none"
        checks.append(f"Native package family: {provider_text} -> {recipe.native_provider} compatible")

    desktop = manifest.get("desktop", {})
    widgets = desktop.get("widget_details", [])
    local_widgets = [item for item in widgets if item.get("source") == "user-local"]
    checks.append(f"Bundled user Plasma widgets: {len(local_widgets)}")
    for widget in local_widgets:
        external = list(widget.get("external_qml_imports") or [])
        if external:
            warnings.append(
                f"Widget {widget.get('id')} uses non-Qt/KDE QML import(s): {', '.join(external)}; "
                "target package availability is not mapped automatically yet."
            )
        minimum = widget.get("plasma_api_minimum_version")
        if minimum:
            checks.append(f"Widget {widget.get('id')} declares Plasma API minimum {minimum}")
            target = recipe.target_plasma_version
            if target and _version_tuple(minimum) > _version_tuple(target):
                blockers.append(
                    f"Widget {widget.get('id')} requires Plasma {minimum}+, but recipe {recipe_id} targets Plasma {target}."
                )

    components = desktop.get("component_details", [])
    local_kwin = [
        item for item in components
        if item.get("kind") in {"kwin-script", "kwin-effect"} and item.get("source") == "user-local"
    ]
    checks.append(f"Active bundled user KWin plugins: {len(local_kwin)}")
    for item in local_kwin:
        checks.append(f"Active {item.get('kind')}: {item.get('name')}")

    required = [item for item in packages if item.get("required_for_appearance")]
    checks.append(f"Required appearance packages: {len(required)}")
    checks.append(
        "Target repository package existence is resolved by KIWI before/directly during the v0.3 build; "
        "cross-release package-name equivalence is still not guessed automatically."
    )

    return PortabilityResult(
        ready=not blockers,
        target_recipe=recipe_id,
        checks=checks,
        warnings=list(dict.fromkeys(warnings)),
        blockers=list(dict.fromkeys(blockers)),
    )
