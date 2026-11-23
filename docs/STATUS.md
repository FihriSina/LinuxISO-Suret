# Current status

**Current release: v0.6.4 - Native QEMU Performance Hardening**

The Native image fidelity work from v0.6.3 is unchanged. v0.6.4 focuses on the acceptance VM itself so a slow QEMU fallback is not confused with a broken ISO.

## v0.6.4 implemented

- Native QEMU memory/CPU sizing adapts to host availability instead of staying fixed at 4096 MiB / 2 vCPU.
- KVM use is printed explicitly; inaccessible or missing `/dev/kvm` emits a prominent TCG warning with host-side diagnostics.
- Acceptance graphics use virtio-vga; disk/network/RNG and supported input devices are paravirtualized.
- Disposable qcow2 test disk uses writeback cache and threaded AIO to reduce installer-copy stalls.
- `LINUX_ISO_QEMU_MEMORY`, `LINUX_ISO_QEMU_CPUS`, `LINUX_ISO_QEMU_DISK_SIZE`, and optional `LINUX_ISO_QEMU_GL=1` provide explicit overrides.
- Fidelity schema remains 12; a profile freshly captured by v0.6.3 can be reused.
- 260 regression tests pass.

## v0.6.3 implemented

- Safe symlink closure for active icon/Plasma/LookAndFeel/cursor/window/GTK/Kvantum appearance packages; profile payload remains symlink-free.
- User-installed KDE Store/manual appearance library preservation, including Tela/Nordic-style variants visible in System Settings.
- Runtime re-application of icon theme, color scheme and Plasma theme without resetting the global desktop layout.
- KDE-style SDDM account synchronization (`kdeglobals`, `plasmarc`, `kcminputrc`, display/font state), system-readable active assets, and first-boot pre-display-manager re-application.
- Per-desktop slideshow schema with runtime DBus convergence after Plasma starts.
- Fidelity schema 12; pre-v12 real profiles require one fresh capture.
- 255 regression tests plus generated-helper/staging syntax validation.

## v0.6.2 implemented

- Fidelity schema v11 preserves `org.kde.slideshow`, `SlidePaths`, slideshow timing/order keys and the complete captured slide collection.
- The initial visible slide can still seed `Image=`, but the wallpaper plugin is no longer converted to `org.kde.image`.
- Runtime Plasma wallpaper state updates the active containment/plugin/path values without destroying slideshow mode.
- SDDM configuration is read using real SDDM precedence: vendor drop-ins, `/etc/sddm.conf.d`, then `/etc/sddm.conf`.
- Custom `ThemeDir` is honored.
- KDE Store SDDM themes with `theme.conf.user` paths into the user's wallpaper folders are made self-contained under the captured theme's `suret-assets/` directory.
- Only image assets are promoted from outside the SDDM theme; browser/profile/credential data remains excluded.
- Theme-internal symlinks are dereferenced safely; links escaping the theme root are ignored.
- Native restore strips only conflicting SDDM `[Theme]` keys from base configuration and installs a low-numbered Suret theme drop-in so later KDE System Settings changes can override it normally.
- SDDM restore is fail-closed when a captured theme cannot be copied or lacks `Main.qml`; Native build exits instead of shipping a white/fallback login screen silently.
- Old real profiles (`fidelity_schema < 11`) require one fresh capture. Retry mode detects this before deleting the previous Native work tree.
- Native application-plan output now reports captured SDDM theme/external-asset count and slideshow collection count.
- 243 regression tests pass.

## v0.6.1 implemented

- Native staging recovers Brave ownership from reversible launcher metadata already present in older profiles.
- ChatGPT/WhatsApp-style web apps use Brave `--app=URL` instead of `xdg-open`, so Zen or another default browser cannot steal the launcher.
- Brave APT installs use Brave Software's official keyring/source descriptor through a code-owned allow-list.
- Browser profile/cookie/history/authentication state remains excluded.
- Old `crx_<app-id>` window-class data is removed when app-id state is intentionally not copied.
- Existing profiles do not require recapture.

## v0.6.0 implemented

- A true Flatpak `com.google.AndroidStudio` capture resolves to the code-owned `google-android-studio` vendor archive adapter; arbitrary profile URLs/commands are never accepted.
- Android Developers metadata is parsed for a Linux archive filename, adjacent SHA-256, and an exact allow-listed Google download host.
- The downloaded archive is SHA-256 verified before extraction; traversal, absolute paths, escaping links, special device/FIFO entries, and privileged archive modes fail closed.
- Android Studio installs under `/opt/android-studio` with real system desktop/icon entries and a launcher command compatible with captured favorites.
- Launcher conversion is scoped to the matching Android Studio desktop entry so other Flatpak `TryExec=flatpak` entries are not rewritten.
- Large vendor downloads use `/var/tmp/linux-iso-vendor`, not the isolated `/run` tmpfs, and are removed after successful deployment.
- Android Studio is removed from the Flatpak plan; if no true Flatpaks remain, Flatpak/bubblewrap installation and sandbox setup are skipped.
- 228 regression tests pass.

## v0.5.9 implemented

- Added a strict vendor-APT resolver allow-list for captured APT `code` and `signal-desktop`.
- Microsoft VS Code is installed from the official Microsoft Code APT repository; Signal Desktop is installed from Signal's official APT repository.
- Selected vendor keys/sources persist in the target so the applications receive normal upstream APT updates.
- Build-time APT sees only official Pardus sources plus explicitly selected vetted vendor sources; no foreign Linux-distribution repository is introduced.
- Native staging restores the original Code/Signal launcher command from reversible capture metadata when their generic Flatpak translation is no longer appropriate.
- Flatpak/bubblewrap are conditional on true Flatpak applications instead of being installed on every Pardus Native image.
- Flatpak and bubblewrap versions are logged; Flatpak 1.16.5 is diagnosed as the known upstream `/proc/self/fd` regression range without adding Debian repositories.
- v0.5.8 host GPU masking, generic GL selection and build-only bubblewrap privilege cleanup remain for true Flatpak captures.
- 220 regression tests pass.

## v0.5.8 implemented

- Chroot `/` is a disposable self bind-mount with slave propagation so bubblewrap can establish its sandbox mount topology.
- Flatpak extra-data deployment uses bubblewrap's documented setuid fallback only while the disposable work tree is sealed `root:root 0700`; normal and failure paths strip setuid before reopening the tree.
- The ROOTFS bind mount can temporarily carry `suid` independently of a `nosuid` parent `/home`; isolated `/run` remains `nosuid,nodev`.
- Build-time Flatpak selection is pinned to the generic `default` GL driver and host `/proc/modules` + `/sys/module` are masked to prevent NVIDIA/AMD build-host extensions from entering the ISO.
- Required Flatpak apps are verified with `flatpak info --system`; a host-specific GPU runtime is a build failure.
- Build-time locale is normalized to `C.UTF-8`; captured end-user locale state is unaffected.
- 213 regression tests pass.

## v0.5.7 implemented

- Native retry/full acceptance safely recover from root-owned work trees created by `unsquashfs` and chroot package installation.
- Known stale chroot mounts under `work/rootfs/{run,sys,proc,dev}` are detached before recursive removal.
- Privileged build cleanup uses `rm --one-file-system`; symlinked pseudo-filesystem paths are never passed to `sudo umount`.
- Custom build paths require a user-owned Suret staging marker before sudo cleanup; the default Native build path remains backward-compatible with v0.5.6 stale work.
- Generated `build-native.sh` uses the same mount-safe reset on direct reruns and successful work cleanup.
- 206 regression tests pass.

## v0.5.6 implemented

- Fixed Native `apt-get update` exit 100 caused by the stock Pardus live-medium APT source being unavailable inside the isolated remaster chroot.
- Build-time APT now uses official Pardus 25 repositories from a temporary source list under `/run/linux-iso/apt-build`.
- Build-time APT list state and source-parts are isolated under `/run`; stale/local-media indexes cannot affect dependency resolution.
- The ISO's `/etc/apt/sources.list*` files are not rewritten, so live boot and `pardus-installer` retain native configuration.
- Translation and Contents indexes are disabled for the remaster package step to reduce metadata downloads.
- 200 regression tests pass.

## v0.5.5 implemented

- Fixed silent Native acceptance/retry exit immediately after `Result:` caused by an expected false `path_within` result becoming the guard function status under `set -e`.
- Native layout checks now use explicit `if` blocks and return success for valid non-overlapping paths.
- Added phase markers before dependency bootstrap, Python sync, profile/probe/staging, build, and QEMU validation.
- Added executable regressions for both safe and unsafe path layouts.
- 196 regression tests pass.

## v0.5.4 implemented

- Required appearance packages are installed and verified separately from optional applications.
- Pardus build support is explicitly gated to Pardus 25 x86_64.
- Profile convergence is fingerprinted and limited to one primary local user; live target-user state is volatile.
- Restore and verification reject symlink traversal/special profile objects; capture redacts generic text and desktop-launcher credential values.
- Generated scripts preserve fail-fast semantics, validate template completion, model post-install free space, preserve SquashFS block size, and guard destructive path overlap.
- Successful Native outputs are atomic, boot-metadata gated, SHA-256 checksummed, and QEMU selects the exact expected ISO.
- Successful builds clean the large work tree unless `LINUX_ISO_KEEP_NATIVE_WORK=1` is requested.
- 192 regression tests pass.

## v0.5.3 implemented

- Fixed false `chroot` dependency failures by normalizing sbin paths across host bootstrap, acceptance, retry, and generated Native build scripts.
- Replaced invalid `xorriso -find ... -print` calls with xorriso-native `-exec echo --`.
- Added xorriso 1.5.6 boot-replay compatibility by selectively mapping only changed live payload/metadata files instead of remapping the full ISO tree.
- Added dedicated regressions for PATH, xorriso traversal, and selective boot-safe remapping.
- 168 regression tests pass.

## v0.5.2 implemented

- Hardened Native Pardus chroot isolation and service-start suppression.
- Required KDE/SDDM install gate and Plasma session verification.
- Pre-SDDM live-profile convergence with no duplicate post-login payload copy.
- Refreshed `filesystem.packages` + `filesystem.size` and added rebuilt-ISO structure verification.
- Compatible OVMF CODE/VARS pairing plus source/base architecture and Pardus major-release gates.
- Version sources synchronized to 0.5.2.
- 162 regression tests pass.

## v0.4.3 implemented

- Removed the build-time HTTP(S) fetch of the Ubuntu archive signing key.
- Bundled and integrity-pinned Ubuntu Archive Automatic Signing Key (2018), fingerprint `F6ECB3762474EDA9D21B7022871920D1991BC93C`.
- KIWI repositories use `this://keys/ubuntu-archive-key-2018.asc`, so repository verification remains enabled without a remote key download.
- Added `ubuntu-keyring` to bootstrap packages so the target image also carries Ubuntu's standard archive trust package.
- Generated `build.sh` verifies the staged key SHA-256 before invoking KIWI.
- 141 regression tests pass.

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
