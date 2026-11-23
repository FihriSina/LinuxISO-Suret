# Linux ISO - Suret v0.5.8 - Flatpak extra-data sandbox hardening

v0.5.8 fixes the first real Native Pardus failure after APT/KDE/application installation reached Flatpak proprietary extra-data deployment. Visual Studio Code failed because Flatpak runs `apply_extra` in a bubblewrap sandbox, while the chroot root was not a mount point and the host kernel restricted unprivileged user namespaces.

## Native sandbox fixes

- Bind-mounts the extracted ROOTFS onto itself and marks it slave before chroot package installation. This gives bubblewrap a real `/` mount on which recursive propagation changes are valid.
- Temporarily remounts only that disposable ROOTFS bind with `suid`, leaving the parent filesystem policy unchanged.
- When Flatpak apps are required, temporarily enables bubblewrap's setuid fallback inside the chroot.
- Seals the disposable work tree as `root:root 0700` before that privilege window, strips setuid on both normal and error paths, then restores the original work-tree owner/mode.
- Final build gates reject any setuid bubblewrap helper left in the target rootfs.
- Interrupted builds remain recoverable by the v0.5.7 privileged retry cleanup; an abruptly interrupted sealed work tree stays inaccessible to the invoking user until reset.

## Host-state isolation

- Uses `LANG=C.UTF-8`, `LC_ALL=C.UTF-8` for build-time package scripts so missing source-host locales no longer flood logs.
- Sets `FLATPAK_GL_DRIVERS=default` during image construction.
- Masks build-host `/proc/modules` and `/sys/module` inside the chroot so NVIDIA/AMD module state cannot select target runtime extensions.
- Fails if versioned NVIDIA/VAAPI-NVIDIA/AMD-AMF host-specific Flatpak runtimes still appear.
- Verifies every required Flatpak application is actually deployed with `flatpak info --system`.

## Validation

- 213/213 regression tests pass.
- Python compile passes.
- All repository shell scripts pass `bash -n`.
- `uv lock --check --offline` passes.
- Generated Pardus Native staging scripts pass shell/Python syntax checks with no unresolved template placeholders.
- The rendered Flatpak install block was simulated for both successful deployment and host-GPU leak rejection; temporary bubblewrap mode was restored in both paths.
