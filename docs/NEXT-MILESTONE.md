# Next milestone - v0.3 ISO validation and fidelity

## Highest priority: prove the ISO

1. Run `linux-iso verify` on a real active-only KDE profile.
2. Stage the Ubuntu 26.04 KDE KIWI project.
3. Build the ISO with KIWI NG on a supported Linux build host.
4. Boot it in QEMU/KVM.
5. Install with Calamares to a disposable virtual disk.
6. Boot the installed system.
7. Compare source and installed Plasma state.
8. Test online and offline application-selection behavior.

## Fidelity work during validation

- validate Panel Colorizer and KdeControlStation payload/config completeness;
- detect enabled KWin scripts/effects so those roots can later become active-only too;
- add safe symlink preservation for theme/icon/widget trees;
- detect custom package-unowned system-wide assets under `/usr/local/share` and `/usr/share`;
- add AppStream display names/icons and download-size estimates to installer choices;
- add a final staged-payload secret scan.

## Installer branding

Use **Linux ISO - Suret** in Calamares-facing product text while keeping technical paths and commands under `linux-iso`.

## Acceptance test

A source desktop containing customized Plasma panels, third-party widgets, a manually downloaded SVG/PNG icon, custom wallpaper/icon/cursor/font state, custom KWin additions and a styled terminal must install into a clean VM without manual desktop reconstruction.


## v0.2.9 exit criteria before v0.3

On the real KDE source machine: scan in active mode, verify with no errors, run portability
for `ubuntu-26.04-kde`, and confirm only enabled user KWin scripts/effects are bundled.
After that, capture/verification behavior is frozen for the first QEMU/KVM ISO cycle.
