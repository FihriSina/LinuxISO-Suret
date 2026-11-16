# Development status

## v0.2.9 implemented

- visible product branding: **Linux ISO - Suret**; repository/package/CLI: `linux-iso`
- uv-based development workflow (`uv sync`, `uv run`, `.python-version`, `uv_build`)
- KDE Plasma configuration, panel/widget, terminal and custom asset capture
- default **active-only** appearance capture with `--asset-mode all` compatibility mode
- active icon theme `Inherits=` dependency traversal
- referenced local plasmoid capture; unused local plasmoids are pruned in active mode
- active icon/cursor/Plasma/color/splash/window-decoration/GTK/Kvantum component resolution
- user fonts, launchers, enabled KWin scripts/effects, tabbox state and hicolor overrides retained
- referenced wallpaper bundle promotion and one-off custom asset capture
- package-owned system widget/component dependencies marked required for appearance
- `linux-iso verify` checksum/dependency/bundle validation
- `stage-iso` blocks profiles with verification errors
- categorized APT/Flatpak/Snap application inventory and Calamares generation
- Ubuntu 26.04 KDE KIWI NG staging recipe

## Verified in this source tree

- Python source compiles successfully.
- Automated tests cover portability, secret redaction, package filtering, KDE metadata aliases, Aurorae resolution, active-only pruning, icon inheritance and profile verification.
- Generated Calamares/first-boot Python remains syntax-checked by tests.

## Not yet verified

- complete KIWI NG ISO build
- QEMU/KVM live boot
- Calamares installation into a disposable virtual disk
- post-install Plasma fidelity comparison

Those are the v0.3 acceptance gates.


## v0.2.7 environment hardening

- Tests run with `uv run --dev python -m pytest -q` rather than depending on the generated `pytest` console script.
- `linux-iso doctor` distinguishes an importable pytest module from a missing console entry point.
- `scripts/repair-env.sh` recreates the project `.venv` deterministically.


## v0.2.8 inherited icon fallback handling

- Unresolved inherited icon themes are recorded as `missing-inherited-fallback`.
- Verification reports them as warnings rather than fatal errors.
- Direct active appearance components still fail verification when unresolved.
- Profile version metadata is synchronized to 0.2.8.


## v0.2.9 portability freeze

- `linux-iso portability` evaluates a verified profile against an ISO recipe.
- User-local KWin scripts/effects are captured only when enabled in `kwinrc`.
- Bundled Plasma widgets record minimum Plasma API, KPackage structure and QML imports.
- Non-Qt/KDE QML imports are surfaced as portability warnings.
- KIWI staging emits `PORTABILITY.txt` and refuses portability blockers.
- Scanner/verification work is intended to freeze after real-system v0.2.9 validation; v0.3 moves to boot/install testing.
