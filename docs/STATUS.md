# Development status

## v0.3.10 implemented

- Added `kiwi-dracut-live` to the Ubuntu 26.04 image package set so KIWI can create the live ISO initrd.

- first executable KIWI ISO build pipeline (`build-doctor`, `build-iso`, staged `build.sh`)
- Pardus prefers the direct Podman KIWI container backend; VM boxbuild/host-direct KIWI remain fallbacks
- the direct container backend avoids both the large first-run QCOW2 VM-box download and the `kiwi.service` orchestration path; standalone `kiwi-boxbuild` remains a fallback
- live user creation, SDDM autologin and desktop Calamares launcher are generated
- captured profile is applied to the live KDE session during KIWI configuration
- direct KIWI builds resolve the package list before image creation
- generated builds use `systemd-inhibit` to block only system sleep/suspend during long builds; desktop idle/lock is untouched
- `test-qemu.sh` boots a generated ISO with KVM or TCG fallback
- recipe-level target Plasma compatibility check for bundled widgets
- Calamares patch helper is self-contained inside the image
- KIWI 11.1.x ISO recipe uses a child `<bootloader name="grub2"/>` element instead of the removed `bootloader=` type attribute

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

Those are now the active v0.3.10 real-system acceptance gates.


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

### Session-safety refinement

- Added `scripts/safe-first-iso.sh` with a transient `org.freedesktop.ScreenSaver` inhibitor.
- The inhibitor is automatically released on normal exit, Ctrl+C, or termination.
- No persistent KDE screen-lock configuration is modified.
- QEMU remains manual after the ISO build.
- Display diagnostics now include current/previous boot kernel DRM, AMDGPU and NVIDIA events.

## v0.3.10 build/schema gate

- KIWI description and result directories are siblings, never nested.
- A successful backend exit without an `.iso` is treated as a build failure.
- A KIWI `image info` preflight log is written before starting boxbuild.
- Container boxbuild runs with debug logging for the next real-system diagnosis.
- Generated KIWI XML has a regression test for the ISO bootloader element shape.

## v0.3.10 Ubuntu archive trust bootstrap

- The source workstation remains Pardus 25 + KDE Plasma; Ubuntu 26.04 KDE is only the current target image base.
- Every Ubuntu APT repository now supplies Canonical's official Ubuntu archive keyring URL to KIWI via the repository signing-key element.
- This fixes the bootstrap failure caused by missing Ubuntu Archive Automatic Signing Key `871920D1991BC93C` in the isolated build container.
