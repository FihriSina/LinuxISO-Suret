# Development status

## v0.2 implemented

- project / CLI renamed to `linux-iso`
- product branding: **Linux ISO — Nakş**
- KDE Plasma configuration capture
- referenced custom SVG/PNG/font/wallpaper asset capture
- terminal configuration capture and shell-secret redaction
- local and package-owned Plasma widget handling
- active KDE icon/cursor/theme/look-and-feel/color-scheme resolution
- application inventory with installer visibility filtering
- Flatpak remote URL preservation
- Snap channel/classic metadata preservation and base-snap filtering
- categorized Calamares `packagechooserq` generation
- architecture-independent custom Calamares Python module search path
- online APT/Flatpak target installation with first-boot fallback
- Ubuntu 26.04 KDE KIWI NG staging recipe
- cross-family native package provider guard
- `inspect`, `audit`, `catalog`, `restore`, and `stage-iso` CLI workflows

## Verified in this source tree

- Python source compiles successfully.
- Automated tests: 5 passing.
- Generated Calamares job, first-boot helper and settings patcher are syntax-checked by the test suite.
- Synthetic profile tests verify custom asset portability and shell-secret redaction.

## Not yet verified

- A complete KIWI NG ISO build in this execution environment.
- QEMU/KVM Live boot.
- Full Calamares installation into a disposable virtual disk.
- Pixel/layout comparison of source and installed Plasma sessions.

Those are the v0.3 acceptance gates. The generated ISO recipe should be treated as experimental until they pass.
