# Linux ISO - Suret v0.5.3 - xorriso 1.5.6 Compatibility

## Runtime blockers fixed

- Normalizes `/usr/local/sbin`, `/usr/sbin`, and `/sbin` into PATH before host dependency checks and generated native builds. This fixes false `chroot` missing reports on desktop sessions whose PATH omits sbin directories.
- Replaces invalid shell-find-style `xorriso -find ... -print` usage with the xorriso-native `-exec echo --` action. This is compatible with the Pardus host's xorriso 1.5.6.
- Avoids remapping the complete extracted ISO tree before `-boot_image any replay`. xorriso 1.5.6 has a known replay bug when a legacy BIOS boot image is replaced by `-map`; Suret now maps only the modified squashfs and live metadata while retaining boot files from the loaded base ISO.

## Native remaster behavior

The base distro remains authoritative for kernel, bootloader, El Torito/MBR/GPT boot equipment, installer, repositories, and distro identity. Suret changes only the live root filesystem and metadata required to describe it.

## Validation

- Regression suite
- Python compile
- `bash -n` for shell scripts and generated scripts
- Offline lock consistency
