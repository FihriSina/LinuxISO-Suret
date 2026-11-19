## v0.3.27 implemented

- Optional application selection is now opt-out: every visible app is selected by default in checkbox-based Calamares category pages.
- Suret preserves Kickoff favorite membership and ordering, including favorite launcher `.desktop` files and icons where available.
- KActivities capture is privacy-scoped: only application favorites and schema metadata are retained; usage/event/score history is stripped and the SQLite database is vacuumed.
- Source avatar plus additional user-visible KDE configuration (KWin rules, KRunner, locale, power management and System Settings state) are captured.
- Slideshow restore picks the most recently accessed source slide as the initial image so a stale Plasma 6 `Image=` entry does not expose the Kubuntu/KDE default wallpaper on first boot.
- Fidelity schema v5 requires a fresh scan.

# Status

## v0.3.25 implemented

- Visual comparison proved that the Plasma panel layout was restored but wallpaper and pinned-launcher assets were incomplete.
- A mandatory target-profile Calamares shellprocess now runs after target-user creation and is independently audited at runtime.
- Plasma pinned `.desktop` launchers are bundled so panel icons survive the Pardus-to-Ubuntu transition.
- Wallpaper directories and individual image references are bundled and rewritten to portable user-local paths; unresolved absolute wallpaper paths are verification errors.
- Fidelity schema v3 forces a fresh source scan before the next ISO build.
- The QEMU helper now supports an `installed` mode for ISO-less QCOW2 boot.
- Full automated suite passes after these changes.

## v0.3.24 implemented

- Real QEMU/Calamares installation completed successfully and the installed QCOW2 system booted without the ISO.
- Strict-fidelity capture now bundles exact active system-owned KDE appearance assets instead of relying only on target-distro package versions.
- Referenced wallpapers/assets outside the source home are copied into portable user-local payload locations and their configuration paths are rewritten.
- Live and target users are cleared of Kubuntu skeleton/vendor personalization before the captured profile is applied.
- Profile-application markers make it possible to verify that the live and installed user actually received the captured payload.
- Calamares-visible Kubuntu product text is rewritten to Linux ISO - Suret while the technical base remains Ubuntu/Kubuntu 26.04.
- v0.3.24 profiles carried fidelity schema v2; v0.3.25 schema v3 requires a fresh scan for launcher/wallpaper-directory fidelity.

## v0.3.23 implemented

- Audited the remaining Kubuntu Calamares execution chain for KIWI-incompatible live-ISO assumptions.
- Replaced the Ubuntu/Kubuntu `packages` cleanup job with a Suret-owned target finalizer that performs no APT or dpkg transactions.
- Removed the duplicate distro `pkgselect` Customize page and its package/snap processing jobs while keeping Suret's categorized `packagechooser` pages.
- Removed Ubuntu live-media-only `add386arch`, `rmcdrom`, and installer-log execution jobs.
- Added target-username handoff so final cleanup safely removes only the temporary `live` user and live-session credentials.
- Added a pre-launch Calamares safety audit that aborts if known unsafe distro jobs remain after runtime patching.
- v0.3.20 kernel-copy, v0.3.21 initramfs, and v0.3.22 automirror compatibility remain unchanged.
- Regression tests cover realistic Kubuntu sequences, instanced package jobs, finalizer idempotence/offline safety, and target-user handoff.

## v0.3.22 implemented

- Added a Calamares `automirror` compatibility job for Ubuntu 26.04 deb822 APT sources.
- The compatibility job creates the legacy `/etc/apt/sources.list` only when missing, immediately before Ubuntu's `automirror` job; automirror then writes `ubuntu.sources` and removes the temporary legacy path normally.
- Existing kernel-copy, initramfs, unpackfs, rsync, UEFI and X11 fixes remain unchanged.
- Regression coverage verifies plain and instanced automirror sequence entries and non-destructive legacy-file handling.

## v0.3.17 implemented

- ISO firmware is explicitly `efi` so KIWI creates the x86_64 EFI boot path instead of the previous BIOS-only default.
- `gpt_hybrid_mbr=true` keeps the generated ISO suitable for both UEFI and legacy BIOS/CSM layouts where supported.
- QEMU validation now uses OVMF/UEFI by default; `LINUX_ISO_QEMU_FIRMWARE=bios` remains available for legacy testing.
- Plasma X11 live-session fallback from v0.3.14 is retained.
- Regression coverage verifies UEFI/hybrid recipe generation and the OVMF test launcher.

## v0.3.14 implemented

- Added a custom KIWI GRUB template: BIOS (`grub_platform=pc`) uses `linux16`/`initrd16`; UEFI keeps `linux`/`initrd`.
- Removed `gfxpayload=keep` from the custom live boot path to avoid carrying a fragile BIOS display handoff.
- Added `plasma-session-x11`, `kwin-x11`, and `xorg` to the Ubuntu 26.04 KDE image recipe.
- Live SDDM now forces X11 and autologins `live` to `plasmax11`.
- QEMU helper now defaults to Q35, standard VGA, GTK without GL, and conservative TCG CPU settings when KVM is unavailable.
- Regression coverage verifies all v0.3.14 boot/session changes.

# Development status

## v0.3.13 implemented

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

Those are now the active v0.3.13 real-system acceptance gates.


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

## v0.3.13 build/schema gate

- KIWI description and result directories are siblings, never nested.
- A successful backend exit without an `.iso` is treated as a build failure.
- A KIWI `image info` preflight log is written before starting boxbuild.
- Container boxbuild runs with debug logging for the next real-system diagnosis.
- Generated KIWI XML has a regression test for the ISO bootloader element shape.

## v0.3.13 Ubuntu archive trust bootstrap

- The source workstation remains Pardus 25 + KDE Plasma; Ubuntu 26.04 KDE is only the current target image base.
- Every Ubuntu APT repository now supplies Canonical's official Ubuntu archive keyring URL to KIWI via the repository signing-key element.
- This fixes the bootstrap failure caused by missing Ubuntu Archive Automatic Signing Key `871920D1991BC93C` in the isolated build container.

## v0.3.13
- Ubuntu bootstrap repositories use HTTP so the empty target root does not require a CA store before `ca-certificates` is installed.
- Repository metadata and packages remain authenticated by Ubuntu archive signing keys and APT hashes.

## v0.3.13 locale bootstrap fix

Ubuntu 26.04 live-image creation now installs `locales-all` before KIWI applies the configured `en_US` locale with `systemd-firstboot`. This prevents the late build failure `Locale en_US.UTF-8 is not installed` after the full KDE/Calamares/kernel package transaction has already completed.

## v0.3.13 GRUB live-ISO boot modules

Ubuntu 26.04 image packages now include `grub-pc-bin` and `grub-efi-amd64-bin`. The BIOS package provides `/usr/lib/grub/i386-pc`, which KIWI requires when creating the live ISO bootloader. The EFI module package is included at the same time so the x86_64 image has both BIOS and UEFI GRUB platform modules available during hybrid ISO creation.
