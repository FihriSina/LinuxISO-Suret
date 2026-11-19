# Linux ISO - Suret v0.5.1

## Native host dependency bootstrap

v0.5.1 removes the first-run host-tool trap from Native ISO Mode.

- `scripts/native-acceptance.sh` now runs a host bootstrap before `probe-iso`.
- On apt-based hosts such as Pardus, missing native remaster/QEMU dependencies are installed automatically in one transaction.
- The complete path is checked, not only `xorriso`: `xorriso`, `squashfs-tools`, `rsync`, `chroot`, `mount/umount`, `qemu-system-x86_64`, `qemu-img`, and OVMF firmware.
- If the host is not apt-based, Suret prints the exact package/tool list instead of failing later one command at a time.
- Dependencies are verified again after installation so the remaster cannot proceed with a partially prepared host.
- Native ISO behavior from v0.5.0 is unchanged: Pardus remains the real base system and Generic KIWI mode remains available separately.

### Fast retry after a host-tool failure

If a previous Native acceptance already created a valid profile and then stopped only because a host dependency was missing, use `scripts/retry-native-acceptance.sh BASE.iso`. It keeps the existing profile and repeats only host bootstrap, native staging, build and QEMU.
