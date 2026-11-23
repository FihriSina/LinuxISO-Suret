# Linux ISO - Suret v0.5.2

## Native remaster hardening

v0.5.2 hardens the first real Pardus Native ISO build before the next acceptance run.

- The chroot no longer bind-mounts the host `/run`; it gets an isolated tmpfs instead, preventing package scripts from reaching host systemd/DBus sockets.
- A temporary `policy-rc.d` blocks service startup during APT package installation and restores any original policy on exit.
- `kde-plasma-desktop` and `sddm` are treated as required Native Pardus packages. A missing/broken core KDE install stops the build instead of silently emitting an XFCE-only ISO.
- Live-user profile convergence is retried immediately before SDDM starts, so panel/theme/wallpaper state can exist before the first Plasma frame.
- First-login convergence detects the pre-login marker and avoids copying the full profile a second time after Plasma is already visible.
- Profile ownership changes are restricted to Suret-managed paths; unrelated files in an existing home are not recursively chowned.
- Native metadata refresh now writes both `filesystem.packages` and `filesystem.size` next to the live rootfs.
- Squashfs compression detection accepts both `Compression xz` and `Compression: xz` output formats.
- ISO checksum regeneration excludes the El Torito boot catalog, which xorriso may regenerate during boot replay.
- Rebuilt ISO structure is checked before acceptance proceeds to QEMU.
- OVMF is considered ready only when a compatible CODE/VARS pair exists; QEMU selects those pairs together.
- Source profile and base ISO architecture are checked before staging; Pardus major release families must also match.
- Generated shell paths are safely quoted.
- Package version metadata is synchronized at `0.5.2`.

## Verification

- 162/162 regression tests pass.
- Python compile checks pass.
- All project shell scripts and generated Native staging scripts pass `bash -n`.
- `uv lock --check --offline` passes.
- Generated Native Python helpers compile successfully.
