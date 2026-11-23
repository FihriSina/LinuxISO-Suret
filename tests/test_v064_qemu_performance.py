from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import linux_iso.builder.native as native
from linux_iso import __version__


def test_v064_version():
    assert __version__ == "0.6.4"


def test_v064_native_qemu_is_resource_adaptive_and_kvm_visible():
    qemu = native.NATIVE_QEMU_SCRIPT
    assert "LINUX_ISO_QEMU_MEMORY" in qemu
    assert "LINUX_ISO_QEMU_CPUS" in qemu
    assert "MemAvailable" in qemu
    assert "HOST_CPUS=$(nproc" in qemu
    assert "QEMU acceleration:" in qemu
    assert "KVM hardware acceleration" in qemu
    assert "TCG software emulation" in qemu
    assert "falling back to slow TCG" in qemu
    assert "-accel kvm -cpu host" in qemu
    assert "-accel tcg,thread=multi" in qemu


def test_v064_native_qemu_uses_virtio_graphics_input_disk_and_rng():
    qemu = native.NATIVE_QEMU_SCRIPT
    assert "-device virtio-vga" in qemu
    assert "virtio-tablet-pci" in qemu
    assert "virtio-keyboard-pci" in qemu
    assert "-device virtio-rng-pci" in qemu
    assert "cache=writeback,aio=threads,discard=unmap" in qemu
    assert "LINUX_ISO_QEMU_GL" in qemu
    assert "virtio-vga-gl" in qemu


def test_v064_native_qemu_template_is_shell_syntax_valid():
    rendered = (
        native.NATIVE_QEMU_SCRIPT
        .replace("__RESULT_Q__", "'/tmp/result'")
        .replace("__OUTPUT_NAME__", "suret.iso")
    )
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "qemu.sh"
        script.write_text(rendered, encoding="utf-8")
        proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr


def test_v064_no_longer_hardcodes_two_cpu_four_gib_qemu_profile():
    qemu = native.NATIVE_QEMU_SCRIPT
    assert '-m 4096 -smp 2' not in qemu
    assert '-m "$QEMU_MEMORY" -smp "$QEMU_CPUS"' in qemu
