## v0.4.2 implemented

- Current Plasma activity/screen 0 is authoritative for visible wallpaper capture.
- SDDM target uses Breeze with captured source wallpaper/avatar; incompatible source QML is archived only.
- Pardus-only and vendor launchers are rewritten to portable KDE/Flatpak/web equivalents.
- Kickoff/panel favorite resolution includes Flatpak and Snap application export roots.
- Fidelity schema v10.
- 138 regression tests pass.

## v0.4.0 implemented

- Added one-command `scripts/final-acceptance.sh` flow.
- QEMU installer test now boots the ISO once and automatically reboots into the installed QCOW2 instead of exiting at Calamares Restart.
- Persistent per-test OVMF VARS state preserves UEFI installer boot entries.
- Added first-login Plasma convergence for visible wallpaper, icon-theme enforcement and KDE application cache refresh.
- Fidelity schema v10 records the current-activity visible wallpaper and runtime-compatible launcher state.
- Optional APT application failures are isolated per package.
- 127 regression tests pass.

## v0.3.33 implemented

- Fixed `safe-first-iso.sh` rejecting freshly captured fidelity schema 8 profiles.
- The build gate now accepts schema 8 and newer, rejects stale/missing schemas explicitly, and has executable regression tests.

## v0.3.32 implemented

- System-visible fidelity now includes source GRUB theme/background settings and SDDM theme assets.
- Target avatars are registered with AccountsService.
- `kio-extras` is included for KDE `computer:/` support.
- Target `~/.local/bin/env` is guaranteed to exist.
- Fidelity schema v8.
- 119 tests pass.

## v0.3.31 implemented

- Installer shortcut is placed on the active XDG desktop directory (Desktop/Masaustu/etc.).
- Source-native launcher naming and v0.3.30 Kubuntu installer masking remain intact.
- Installed-system boot mode remains unchanged.
