# Linux ISO - Suret v0.5.4 - Native Deep Hardening

v0.5.4 is a batch hardening release for the Pardus 25 Native ISO path. It keeps the native-remaster architecture introduced in v0.5.0 and the xorriso 1.5.6 compatibility work from v0.5.3, while closing the next group of fidelity, safety, multi-user, disk-space and result-integrity failure modes before the next real Pardus 25.2 acceptance run.

## Native fidelity and application resolution

- Packages marked `required_for_appearance` are now a separate mandatory install plan. A source theme/widget/icon/font package can no longer be skipped merely because it is not an optional user application.
- Required appearance packages are checked against the native Pardus repositories and verified with `dpkg-query` after installation. Missing appearance dependencies fail early rather than producing a silently degraded desktop.
- Known Snap/vendor applications can resolve to explicit Flatpak fallbacks; unknown Snap applications fail staging instead of leaving dead launchers.
- Native APT package names and Flatpak IDs are validated before shell generation.
- The Pardus build-capable adapter is explicitly limited to Pardus 25 x86_64. Future Pardus releases remain probe-only until they receive their own repository/adapter policy.

## Profile convergence and multi-user safety

- Pre-login and first-login restore markers are tied to the SHA-256 fingerprint of the current manifest, so stale markers cannot suppress a newer profile.
- A native profile is applied to one primary local interactive account only, not every UID in the user range.
- Live media keeps the chosen target-user marker under `/run`; installed systems use `/var/lib/linux-iso/target-user`. An ephemeral live username therefore cannot become persistent target state.
- SDDM autologin consumes the same live target-user marker used by pre-login restore.
- Restore refuses to traverse existing symlink parents in the target home and uses non-following ownership changes.
- Staging deletes an older staged profile before copying the new one, preventing stale launchers/assets from surviving a re-stage.

## Profile and secret-safety hardening

- Verification rejects symbolic links and special files anywhere in a profile and rejects traversal-style manifest destinations.
- Manifest symlinks are rejected before they can be read; payload checksums no longer follow symlink components outside the profile.
- Sensitive-path matching is case-insensitive and covers additional browser and credential stores such as `.aws`, `.docker`, `.kube`, `.mozilla`, Chromium/Chrome/Brave stores and credential directories.
- Secret-assignment redaction is applied to all captured text configuration files, not shell files only.
- Desktop launcher commands redact credential-like inline arguments and authenticated URL query values before portable launcher rewriting or reversible Exec metadata is stored.
- GRUB/SDDM visual metadata is validated before being used as a path or configuration value, preventing path traversal/newline injection from a corrupted profile.
- System visual tree capture no longer follows symlinks out of a theme directory.

## Native build robustness

- Chroot cleanup helpers run in subshells so `set -e` remains active after cleanup; mksquashfs/xorriso/metadata failures remain fatal.
- `/run` remains an isolated tmpfs, `/sys` is a fresh read-only sysfs mount, `/dev` is recursively bound, and `policy-rc.d` suppresses package-service starts.
- The host bootstrap now validates the helper commands the generated build actually uses (`readlink`, `stat`, `df`, `du`, `find`, `xargs`, `awk`, `grep`, checksums, and others) in addition to xorriso/squashfs/QEMU/OVMF.
- Acceptance uses `uv sync --frozen`, preventing an acceptance run from rewriting dependency resolution.
- Generated templates are rejected at staging time if an unresolved `__TOKEN__` remains.
- The original SquashFS compression and block size are preserved when discoverable.
- A second, post-install free-space model estimates the rebuilt SquashFS and output ISO after KDE/application growth, catching likely ENOSPC failures before repack.
- Successful builds remove the large extracted work tree by default. `LINUX_ISO_KEEP_NATIVE_WORK=1` preserves it for manual inspection.
- Destructive work/build/result paths are checked for dangerous overlap so a custom work path cannot contain the base ISO, staged project, profile or final result.

## Output and boot integrity

- The remastered ISO is written to a `.partial` path and is promoted to the final filename only after structural and boot metadata checks pass.
- xorriso 1.5.6-compatible selective mapping remains in place: boot-image files are preserved from the base ISO while only changed live payload/metadata files are replaced.
- BIOS/UEFI El Torito and MBR/GPT/APM system-area characteristics present on the base ISO are hard-gated on the remastered image.
- The rebuilt SquashFS is structurally checked before ISO repack.
- Every successful ISO receives a relocatable `.sha256` file.
- QEMU launches the exact expected Native output filename and validates its checksum instead of choosing the newest arbitrary ISO in the result directory.
- `native-build.log` and `native-boot-report.txt` remain available in the result directory for batch diagnosis.

## Validation

- 192 regression tests pass.
- Generated Native shell scripts pass `bash -n` in staging smoke tests.
- Generated pre-login, first-login and system-visual Python helpers compile successfully.
- Project Python sources compile successfully.
- Version sources are synchronized at 0.5.4.

The next real-system step is still a single retry using the already verified profile:

```bash
cd ~/Kodlama/LinuxISO-Suret

./scripts/retry-native-acceptance.sh \
  "$HOME/İndirilenler/Pardus-25.2-XFCE-amd64.iso"
```
