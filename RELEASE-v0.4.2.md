# Linux ISO - Suret v0.4.2

This release is a batch runtime-compatibility pass driven by the installed-system screenshots rather than a one-error-per-version patch.

## Fixed together

- **Wrong wallpaper:** the scanner now queries the current Plasma activity and screen 0 first, avoiding stale/dormant containments.
- **Blank/white SDDM:** the target activates the Plasma 6 Breeze SDDM shell with the captured source wallpaper and avatar. The source SDDM theme is archived but not blindly activated across distro/Qt boundaries.
- **Broken `Bilgisayar`:** the Pardus-only launcher is rewritten to a portable Dolphin filesystem view rather than the unavailable historical `computer:/` protocol.
- **Pardus-only launchers:** About/Hardware Info, Update, Software Center, Power Manager and Java Installer entries are mapped to target KDE equivalents while retaining their visible labels/icons.
- **VS Code / Signal / Steam:** source vendor package launchers are rewritten to stable Flathub identities and the installer catalog selects those Flatpak providers by default.
- **ChatGPT / WhatsApp Web:** browser-profile-specific launchers are normalized to `xdg-open` web URLs.
- **Missing Flatpak favorites:** pinned/favorite `.desktop` files are resolved from user/system Flatpak export roots and Snap desktop exports in addition to normal XDG application roots.
- **Runtime support:** `xdg-utils`, Flatpak, Plasma Discover Flatpak backend, Info Center and Breeze SDDM theme are part of the target image.
- **Stale profiles:** fidelity schema v10 requires a fresh capture for these runtime mappings.

## Verification

- 138/138 regression tests pass.
- Modified Python modules compile successfully.
- Project and generated shell scripts pass `bash -n`.

## Acceptance

Replace the project tree with this release and run:

```bash
cd ~/Kodlama/LinuxISO-Suret
./scripts/final-acceptance.sh
```

The command performs a fresh scan/verify/audit/portability pass, builds the ISO, starts a clean installer VM, and keeps the same QEMU instance across installer reboot into the installed system.

If anything remains, run `suret-diagnose` once inside the installed system and send its single generated archive for the next batch pass.
