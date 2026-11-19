from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

from linux_iso.assets import sha256_file
from linux_iso.branding import PRODUCT_NAME


@dataclass
class VerificationResult:
    ok: bool
    stats: dict[str, int | str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def render(self) -> str:
        status = "PASS" if self.ok and not self.warnings else "PASS WITH WARNINGS" if self.ok else "FAIL"
        lines = [
            f"{PRODUCT_NAME} profile verification",
            "=" * 36,
            f"Status: {status}",
            "",
            "Checks",
            "------",
            f"- Asset mode: {self.stats.get('asset_mode', 'unknown')}",
            f"- Manifest payload entries: {self.stats.get('manifest_files', 0)}",
            f"- Payload files present: {self.stats.get('present_files', 0)}",
            f"- Checksums verified: {self.stats.get('verified_checksums', 0)}",
            f"- Appearance components: {self.stats.get('components', 0)}",
            f"- Referenced widgets: {self.stats.get('widgets', 0)}",
            f"- Required appearance packages: {self.stats.get('required_packages', 0)}",
        ]
        lines.extend(["", "Warnings", "--------"])
        if self.warnings:
            lines.extend(f"- {item}" for item in self.warnings)
        else:
            lines.append("(none)")
        lines.extend(["", "Errors", "------"])
        if self.errors:
            lines.extend(f"- {item}" for item in self.errors)
        else:
            lines.append("(none)")
        return "\n".join(lines)


def _load_manifest(profile: Path) -> dict[str, Any]:
    path = profile / "manifest.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Missing profile manifest: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _payload_path(profile: Path, destination: str, placeholder: str) -> Path | None:
    prefix = placeholder + "/"
    if destination == placeholder:
        return profile / "payload/home"
    if not destination.startswith(prefix):
        return None
    return profile / "payload/home" / destination[len(prefix) :]


def _bundle_has_payload(destinations: set[str], root: str) -> bool:
    normalized = root.rstrip("/")
    return normalized in destinations or any(item.startswith(normalized + "/") for item in destinations)


def verify_profile(profile: Path) -> VerificationResult:
    profile = profile.expanduser().resolve()
    manifest = _load_manifest(profile)
    desktop = manifest.get("desktop", {})
    restore = manifest.get("restore", {})
    placeholder = restore.get("home_placeholder", "{{HOME}}")
    payload_root = profile / "payload/home"

    warnings: list[str] = []
    errors: list[str] = []
    try:
        fidelity_schema = int(restore.get("fidelity_schema", 0) or 0)
    except (TypeError, ValueError):
        fidelity_schema = 0
    if fidelity_schema < 4:
        warnings.append(
            "Profile predates strict-fidelity capture v4; re-run 'linux-iso scan' before the next ISO build "
            "to repair moved wallpaper references as well as bundle launcher/wallpaper assets."
        )
    stats: dict[str, int | str] = {
        "asset_mode": restore.get("asset_mode", "legacy/all"),
        "manifest_files": 0,
        "present_files": 0,
        "verified_checksums": 0,
        "components": len(desktop.get("component_details", [])),
        "widgets": len(desktop.get("widget_details", [])),
        "required_packages": 0,
    }

    if not payload_root.is_dir():
        errors.append("payload/home is missing.")

    entries = list(desktop.get("configs", [])) + list(desktop.get("custom_assets", []))
    stats["manifest_files"] = len(entries)
    destinations: set[str] = set()
    for item in entries:
        destination = str(item.get("destination") or "")
        if not destination:
            errors.append("A captured file has no destination.")
            continue
        if destination in destinations:
            errors.append(f"Duplicate payload destination in manifest: {destination}")
            continue
        destinations.add(destination)
        path = _payload_path(profile, destination, placeholder)
        if path is None:
            errors.append(f"Non-portable payload destination: {destination}")
            continue
        if not path.is_file():
            errors.append(f"Missing payload file: {destination}")
            continue
        stats["present_files"] = int(stats["present_files"]) + 1
        expected = item.get("sha256")
        if expected:
            actual = sha256_file(path)
            if actual != expected:
                errors.append(f"Checksum mismatch: {destination}")
            else:
                stats["verified_checksums"] = int(stats["verified_checksums"]) + 1

    packages = manifest.get("packages", [])
    package_index = {
        (str(item.get("provider")), str(item.get("name"))): item
        for item in packages
        if item.get("provider") and item.get("name")
    }
    required = [item for item in packages if item.get("required_for_appearance")]
    stats["required_packages"] = len(required)

    for component in desktop.get("component_details", []):
        label = f"{component.get('kind')}={component.get('name')}"
        source = component.get("source")
        if source == "not-found":
            # Backward compatibility for profiles captured before v0.2.8: an
            # unresolved *inherited* icon fallback used to be serialized as a
            # generic not-found component. It is not equivalent to the directly
            # active icon theme being missing, so downgrade only this precise
            # legacy case to a warning.
            if component.get("kind") == "icon-theme" and component.get("inherited"):
                parent = component.get("inherited_from")
                suffix = f" (inherited from {parent})" if parent else ""
                warnings.append(
                    f"Inherited icon fallback is not installed as a standalone theme: {label}{suffix}; "
                    "the captured active theme and remaining fallback chain will be used."
                )
                continue
            errors.append(f"Active appearance component could not be resolved: {label}")
            continue
        if source == "missing-meta-package":
            warnings.append(
                f"Global theme meta-package is absent for {label}; captured subcomponents will be used."
            )
            continue
        if source == "missing-inherited-fallback":
            parent = component.get("inherited_from")
            suffix = f" (inherited from {parent})" if parent else ""
            warnings.append(
                f"Inherited icon fallback is not installed as a standalone theme: {label}{suffix}; "
                "the captured active theme and remaining fallback chain will be used."
            )
            continue
        if component.get("bundled"):
            root = component.get("bundle_root")
            if root and not _bundle_has_payload(destinations, str(root)):
                errors.append(f"Bundled appearance component has no payload files: {label} ({root})")
        if source == "system-package":
            key = (str(component.get("provider")), str(component.get("package")))
            package = package_index.get(key)
            if package is None or not package.get("required_for_appearance"):
                errors.append(f"Appearance package is not marked required: {key[0]}:{key[1]} for {label}")

    for widget in desktop.get("widget_details", []):
        label = str(widget.get("id"))
        source = widget.get("source")
        if source == "not-found":
            errors.append(f"Referenced Plasma widget could not be resolved: {label}")
            continue
        if widget.get("bundled"):
            root = widget.get("bundle_root")
            if root and not _bundle_has_payload(destinations, str(root)):
                errors.append(f"Bundled Plasma widget has no payload files: {label} ({root})")
        if source == "system-package":
            key = (str(widget.get("provider")), str(widget.get("package")))
            package = package_index.get(key)
            if package is None or not package.get("required_for_appearance"):
                errors.append(f"Widget package is not marked required: {key[0]}:{key[1]} for {label}")

    # Strict-fidelity v3 must not silently leave wallpaper references pointing
    # back to paths that are absent from the portable payload.  Plasma otherwise
    # falls back to the target distribution wallpaper, which looks like a
    # successful restore even though visual fidelity was lost.
    plasma_config = payload_root / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if fidelity_schema >= 3:
        if not plasma_config.is_file():
            warnings.append("Strict-fidelity profile has no Plasma desktop/panel configuration to validate.")
        else:
            try:
                plasma_text = plasma_config.read_text(encoding="utf-8", errors="replace")
            except OSError:
                plasma_text = ""
            for line in plasma_text.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() not in {"Image", "SlidePaths"}:
                    continue
                values = [value] if key.strip() == "Image" else value.replace(";", ",").split(",")
                for raw in values:
                    decoded = unquote(raw.strip())
                    if decoded.startswith("file://"):
                        decoded = decoded[7:]
                    prefix = placeholder + "/"
                    if decoded.startswith(prefix):
                        candidate = payload_root / decoded[len(prefix):]
                        if not candidate.exists():
                            errors.append(f"Wallpaper reference has no payload asset: {decoded}")
                    elif decoded.startswith("/"):
                        errors.append(
                            f"Strict-fidelity wallpaper reference was not made portable: {decoded}"
                        )

    # Report payload files that exist but are not described by the manifest. They
    # are not fatal, but reproducibility is weaker because checksums are missing.
    if payload_root.is_dir():
        actual_payload_files = {path for path in payload_root.rglob("*") if path.is_file()}
        described_files = {
            path
            for item in entries
            if (path := _payload_path(profile, str(item.get("destination") or ""), placeholder)) is not None
        }
        extras = actual_payload_files - described_files
        if extras:
            warnings.append(f"{len(extras)} payload file(s) exist without manifest entries.")

    return VerificationResult(ok=not errors, stats=stats, warnings=warnings, errors=errors)
