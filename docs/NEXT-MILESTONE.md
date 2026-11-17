# Next milestone - v0.3.15 UEFI live boot and installer validation

## Highest priority: prove the ISO

1. Run `linux-iso verify` on a real active-only KDE profile.
2. Run `linux-iso build-doctor` and prefer the direct Podman container backend and fall back to VM/host-direct backends.
3. Run `linux-iso build-iso` for the Ubuntu 26.04 KDE recipe.
4. Boot the resulting ISO with generated `test-qemu.sh`.
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

## v0.3.14 next check
- Re-run the container build and confirm the bootstrap proceeds past APT package download into image configuration.


## v0.3.15 validation target

1. Build the ISO with the `firmware=efi` hybrid recipe.
2. Boot it through OVMF using the generated `test-qemu.sh`.
3. Confirm the live Plasma X11 desktop appears automatically.
4. Launch Calamares and complete installation in a clean VM.
