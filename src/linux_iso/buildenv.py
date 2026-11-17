from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from linux_iso.branding import PRODUCT_NAME
from linux_iso.system import parse_os_release


SUPPORTED_DIRECT_IDS = {"ubuntu", "debian", "fedora", "opensuse-tumbleweed", "opensuse-leap", "arch"}


@dataclass
class BuildHostReport:
    recommended_backend: str | None
    checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.recommended_backend is not None and not self.blockers

    def render(self) -> str:
        status = "READY" if self.ready and not self.warnings else "READY WITH WARNINGS" if self.ready else "NOT READY"
        lines = [
            f"{PRODUCT_NAME} build host doctor",
            "=" * 35,
            f"Status: {status}",
            f"Recommended backend: {self.recommended_backend or 'none'}",
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


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _kvm_accessible() -> tuple[bool, str]:
    path = Path("/dev/kvm")
    if not path.exists():
        return False, "/dev/kvm is missing"
    if os.access(path, os.R_OK | os.W_OK):
        return True, "/dev/kvm is readable and writable"
    return False, "/dev/kvm exists but the current user cannot read/write it"


def build_host_report() -> BuildHostReport:
    release = parse_os_release()
    distro_id = (release.get("ID") or "unknown").lower()
    distro_like = (release.get("ID_LIKE") or "").lower()
    pretty = release.get("PRETTY_NAME") or release.get("NAME") or distro_id
    arch = platform.machine()

    checks: list[str] = [f"Host: {pretty} ({arch})"]
    warnings: list[str] = []
    blockers: list[str] = []

    podman = _tool("podman")
    uv = _tool("uv")
    kiwi_boxbuild = _tool("kiwi-boxbuild")
    kiwi_ng = _tool("kiwi-ng")
    qemu = _tool("qemu-system-x86_64") or _tool("qemu-kvm")
    kvm_ok, kvm_text = _kvm_accessible()

    checks.append(f"podman: {podman or 'not found'}")
    checks.append(f"uv: {uv or 'not found'}")
    checks.append(f"kiwi-boxbuild: {kiwi_boxbuild or 'not found'}")
    checks.append(f"kiwi-ng: {kiwi_ng or 'not found'}")
    checks.append(f"qemu: {qemu or 'not found'}")
    checks.append(f"KVM: {kvm_text}")

    try:
        free_gib = shutil.disk_usage(Path.home()).free / (1024 ** 3)
        checks.append(f"Free space in home filesystem: {free_gib:.1f} GiB")
        if free_gib < 20:
            warnings.append("Less than 20 GiB free space is available; a KDE ISO build may run out of space.")
    except OSError:
        pass

    direct_supported = distro_id in SUPPORTED_DIRECT_IDS
    if distro_id == "pardus" or "pardus" in distro_like:
        direct_supported = False
    if not direct_supported:
        warnings.append(
            f"Direct KIWI builds are not treated as validated on host distro '{distro_id}'; "
            "the isolated container backend is preferred for cross-distro builds."
        )

    recommended: str | None = None
    if podman and uv:
        recommended = "container"
        checks.append("Direct KIWI container mode: official build box via Podman")
        checks.append("Container mode runs kiwi-ng system build directly and avoids the VM/QCOW2 box path")
        if not qemu:
            warnings.append("QEMU is not installed on the host; ISO build can proceed, but local boot testing is unavailable.")
    elif kiwi_boxbuild and podman and kvm_ok:
        recommended = "boxbuild"
        checks.append("Boxbuild mode: standalone kiwi-boxbuild")
        checks.append("Standalone kiwi-boxbuild does not require host python3-kiwi or kiwi-systemdeps-boxbuild")
        if not qemu:
            warnings.append("QEMU is not installed on the host; ISO build can proceed, but local boot testing is unavailable.")
    elif kiwi_ng and podman and qemu and kvm_ok:
        recommended = "boxbuild"
        checks.append("Boxbuild mode: kiwi-ng system boxbuild")
    elif kiwi_ng:
        recommended = "direct"
        if not direct_supported:
            warnings.append("Falling back to direct kiwi-ng on an unvalidated host distribution.")
    else:
        blockers.append(
            "No usable KIWI build backend was found. On Pardus 25 run "
            "./scripts/install-build-deps-pardus.sh. Preferred path: uv + podman direct container build."
        )

    if uv and not podman:
        warnings.append("uv is present but Podman is missing; direct container build is unavailable.")
    if kiwi_boxbuild and not podman:
        warnings.append("kiwi-boxbuild is present but podman is missing.")
    if kiwi_ng and podman and not qemu:
        warnings.append("kiwi-ng + podman are present, but QEMU is missing for core boxbuild.")
    if recommended == "boxbuild" and kiwi_boxbuild and not kvm_ok:
        warnings.append("kiwi-boxbuild is present but KVM access is unavailable; VM boxbuild cannot use hardware acceleration.")

    return BuildHostReport(
        recommended_backend=recommended,
        checks=checks,
        warnings=list(dict.fromkeys(warnings)),
        blockers=list(dict.fromkeys(blockers)),
    )
