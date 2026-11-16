# Development status

## v0.2.3 implemented

- uv-based development workflow (`uv sync`, `uv run`, `.python-version`, `uv_build`)
- project / CLI name: `linux-iso`; product branding: **Linux ISO — Nakş**
- KDE Plasma configuration, panel/widget, terminal and custom asset capture
- user-local and package-owned Plasma widget handling
- active KDE icon/cursor/theme/look-and-feel/color-scheme/window-decoration resolution
- missing global-theme meta packages are distinguished from actually missing active subcomponents
- metadata-aware KDE component lookup (directory name plus package Id/Name)
- audit asset bundling so complete icon and Aurorae window-decoration themes no longer print as hundreds of individual SVG rows
- standalone custom referenced assets remain individually auditable
- stricter native package chooser filtering for libraries, runtimes, microcode, headers and `-dev` packages
- false-positive fixes for names such as `microcode`/`libfishcamp`
- `.desktop` category metadata used where available; Flatpak app-id fallback rules improved
- Flatpak remote URL preservation and Snap channel/classic metadata preservation
- categorized Calamares `packagechooserq` generation
- online APT/Flatpak target installation with first-boot fallback
- Ubuntu 26.04 KDE KIWI NG staging recipe
- `inspect`, `audit`, `catalog`, `restore`, and `stage-iso` CLI workflows

## Verified in this source tree

- Python source compiles successfully.
- Automated tests: 11 passing.
- Regression tests cover package-name false positives, KDE metadata-id theme resolution, Aurorae decoration detection and audit asset grouping.
- Generated Calamares job, first-boot helper and settings patcher remain syntax-checked by the test suite.
- Synthetic profile tests verify custom asset portability and shell-secret redaction.

## uv lock note

This execution environment cannot access PyPI, so a fresh `uv.lock` cannot be generated here when the required registry metadata is not already cached. On a connected developer machine, `uv sync` generates/updates the lockfile normally; it should be committed to the repository.

## Not yet verified

- A complete KIWI NG ISO build.
- QEMU/KVM Live boot.
- Full Calamares installation into a disposable virtual disk.
- Pixel/layout comparison of source and installed Plasma sessions.

Those are the v0.3 acceptance gates.
