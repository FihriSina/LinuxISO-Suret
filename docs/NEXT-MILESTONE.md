# Next milestone - v0.6.0 Native Pardus acceptance

The next validation target is the first full Pardus 25.2 Native ISO remaster using the already captured and verified profile.

Run only:

```bash
cd ~/Kodlama/LinuxISO-Suret

./scripts/retry-native-acceptance.sh \
  "$HOME/İndirilenler/Pardus-25.2-XFCE-amd64.iso"
```

The retry must reuse `~/linux-iso-profile`; it must not rescan the source desktop.

Expected Native chain:

1. Host dependency bootstrap validates the complete generated-build toolset and a compatible OVMF CODE/VARS pair.
2. The Pardus ISO is probed and source/base distro, architecture, and Pardus major-release compatibility are checked.
3. The official Pardus live rootfs is extracted.
4. Chroot package installation runs on a self bind-mounted root with isolated `/run`, masked host module state, service-start suppression, and build-only Flatpak/bubblewrap hardening.
5. KDE Plasma + SDDM and all source appearance packages are required to install successfully. Captured APT Code/Signal resolve through vetted vendor APT repositories. Captured Flatpak Android Studio resolves through the vetted official Google Linux archive with SHA-256 + safe-extraction gates; only remaining true Flatpaks enter Flatpak/bubblewrap.
6. Suret profile state is embedded and applied before SDDM to one primary target user; live target-user state remains under `/run`.
7. `filesystem.packages`, `filesystem.size`, squashfs, and checksums are rebuilt; only changed live payload files are mapped back into the loaded base ISO so xorriso 1.5.6 does not replace legacy boot-image files before boot replay.
8. The remastered ISO is structurally/boot verified, SHA-256 checksummed, and the exact verified output is then opened in QEMU.

QEMU acceptance criteria:

- System identity remains Pardus.
- Pardus installer remains available.
- Plasma is the active desktop while XFCE remains installed by default.
- Source wallpaper, panel/Kickoff state, avatar, icons, cursor, fonts, themes, and visible desktop launchers converge without a post-login visual jump.
- Pardus-native launchers use their original commands.
- Portable/vendor applications have a real installed runtime; no dead launcher is accepted.
- Installed-system boot preserves the same profile and does not leak personal/credential data.

If the command fails, preserve the complete terminal output. Debug the surrounding Native build stage in one batch rather than patching only the final error line.

## Later scope

- Optional `--replace-base-desktop` acceptance after the default KDE+XFCE path is stable.
- Debian/Ubuntu-family Native adapter generalization.
- Fedora/Anaconda Native adapter.
- GUI workflow for ISO selection, scan, build, and validation.
