# Linux ISO - Suret v0.6.4

## Native QEMU Performance Hardening

v0.6.4 does not change the captured profile format or the Native remaster contents. It fixes the acceptance VM becoming unresponsive after the image grew into a full Plasma system with vendor applications, appearance libraries and installer-time I/O.

### Root cause

The generated Native QEMU launcher still used a fixed 4096 MiB RAM, 2 vCPU profile with the default legacy display path. More importantly, when `/dev/kvm` was unavailable to the current user, it silently fell back to TCG software CPU emulation. During Pardus installation, PackageKit/update scanning and multi-gigabyte filesystem copies, that can make Plasma clicks appear to be ignored.

### Changes

- Host-adaptive QEMU memory and vCPU sizing, with `LINUX_ISO_QEMU_MEMORY` and `LINUX_ISO_QEMU_CPUS` overrides.
- Explicit `KVM hardware acceleration` / `TCG software emulation` startup banner.
- Clear diagnostic when `/dev/kvm` exists but is not accessible, or is absent.
- Virtio VGA plus virtio disk/network/RNG and supported paravirtual pointer/keyboard devices.
- qcow2 writeback cache + threaded AIO for the disposable installer test disk.
- Optional `LINUX_ISO_QEMU_GL=1` virgl path; 2D virtio remains the compatibility default.
- `LINUX_ISO_QEMU_DISK_SIZE` override for the disposable acceptance disk.
- Fidelity schema remains 12; profiles freshly captured for v0.6.3 do not need another scan.

### Validation

- 260/260 regression tests pass.
- Python compile passes.
- All repository shell scripts pass `bash -n`.
- `uv lock --check --offline` passes.
- Generated Native QEMU launcher passes `bash -n` after template rendering.
