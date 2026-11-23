# Linux ISO - Suret architecture

Linux ISO separates **personalization state** from **hardware/system identity** and now has two build modes.

## Primary path: Native ISO Mode (v0.5.0+)

```text
Running personalized Linux desktop
          │
          ▼
      Capture Core
          │
          ▼
   Portable Profile
          │
          ├──────────── user supplies official distro ISO
          │                         │
          ▼                         ▼
  Native ISO Adapter ──────► probe distro / live rootfs / installer
          │
          ▼
  unpack native live rootfs
          │
          ├── install missing target desktop inside the SAME distro
          ├── install portable/source applications when resolvable
          ├── embed Suret profile and first-login convergence
          └── preserve distro kernel, repositories, bootloader and installer
          │
          ▼
   repack native ISO
```

Pardus 25 `/live/filesystem.squashfs` is the first build-capable native adapter. A KDE profile on a Pardus XFCE base installs KDE into Pardus; it does **not** change the base to Ubuntu.

Native mode intentionally refuses silent cross-distro grafting. If the profile was captured from Pardus, the selected native base must also be Pardus. Native staging also rejects architecture mismatches and, for Pardus, mismatched major release families before unpacking the ISO.

Native chroot package installation is isolated from the host runtime: `/run` is a private nosuid tmpfs, `/sys` is a fresh read-only sysfs, `/dev` is recursively bound for device/PTY availability, and Debian-family service startup is suppressed with a temporary `policy-rc.d`. The chroot root itself is a disposable self bind-mount with slave propagation so nested sandbox tools can safely alter mount propagation. Build-time `/proc/modules` and `/sys/module` are masked so package/Flatpak resolution cannot encode the build host's loaded GPU/kernel modules into the image.

v0.5.8 adds a narrowly scoped Flatpak extra-data compatibility window for hosts that block unprivileged user namespaces: bubblewrap may be made setuid only while the disposable work tree is sealed `root:root 0700`. All ordinary success/failure paths sanitize the helper before the tree is exposed, and the final ISO gate rejects a retained setuid bubblewrap helper. Flatpak GL driver selection is forced to the generic `default` extension during image construction.

v0.5.9 separates source-provider fidelity from portability fallback. Captured APT applications use the distro repository when available, then a compiled allow-list of official vendor APT repositories for known vendor packages such as VS Code and Signal. APT packages are not automatically converted to Flatpak merely because the clean base ISO lacks the source machine's vendor repository. Applications genuinely captured as Flatpak remain Flatpak. Vendor repository URLs, key locations and package names are code-owned metadata rather than profile-controlled input, and no foreign Linux-distribution repository is added to Pardus. Flatpak runtime packages are installed only when the rendered plan contains true Flatpak applications.

v0.6.0 adds a code-owned vendor-archive resolver for a narrower case: a genuinely captured Flatpak may use proprietary `extra-data` whose install-time sandbox is incompatible with the target distro's Flatpak branch. `com.google.AndroidStudio` is resolved through Android Developers rather than a foreign package repository. Suret accepts only exact Google download hosts, requires the published SHA-256, rejects unsafe tar members/links/privileged modes, installs under `/opt/android-studio`, and rewrites only the matching launcher. Large archive staging uses `/var/tmp`, not the private `/run` tmpfs. Applications without an explicit vetted resolver remain on their captured provider path and still fail closed if they cannot actually be installed.

v0.6.2 raises visual fidelity to schema 11. Plasma slideshow containments retain their original `org.kde.slideshow` plugin, portable `SlidePaths`, interval/order configuration, and captured image directories; the current/most-recent slide is only an initial `Image=` seed. SDDM capture follows SDDM's actual configuration precedence and honors custom `ThemeDir`. User-selected login backgrounds referenced from `theme.conf.user` are copied into a self-contained theme bundle, while arbitrary files and external symlink targets remain excluded. Native restore removes only competing `[Theme]` keys from the base SDDM configuration, installs the captured theme as `suret-source`, and fails closed if the theme cannot be restored. Real profiles captured before schema 11 are not guessed/migrated automatically because older Suret versions intentionally flattened slideshows to static wallpapers.

v0.6.3 raises fidelity to schema 12 and makes the visual state convergent rather than config-copy-only. Appearance-package capture safely dereferences symlinks only inside trusted KDE theme roots, so symlink-heavy icon sets retain their real assets while the profile itself remains inert and symlink-free. Active mode also carries the user-visible KDE Store/manual appearance library. Native first login re-applies icon/color/Plasma theme state after plasmashell exists, and restores slideshow settings through Plasma's scripting DBus interface. SDDM restoration mirrors KDE's own Plasma-settings sync into the dedicated `sddm` account, promotes required user-local assets to system-readable locations, and runs once more before the display manager on the first Live/installed boot to survive installer post-processing.

v0.6.4 leaves the remaster/profile schema unchanged and hardens only the acceptance VM. The generated QEMU launcher selects KVM when `/dev/kvm` is usable and visibly reports TCG fallback otherwise, sizes RAM/vCPU from host availability with explicit overrides, and uses virtio graphics/storage/network/RNG/input devices. This prevents acceptance-only virtualization bottlenecks from being misdiagnosed as failures in the remastered Pardus desktop.


v0.5.4 treats appearance packages as mandatory fidelity dependencies and restores the captured profile to one primary local account only. Live target-user selection is volatile under `/run`; installed target selection is persisted under `/var/lib/linux-iso`. Profile verification rejects symlinks/special files and traversal destinations before root staging. Native output is produced atomically, boot metadata is compared against the base image, and the final ISO receives a SHA-256 checksum before QEMU validation.

## Secondary path: Generic Build Mode

The existing KIWI + Ubuntu/Kubuntu + Calamares pipeline remains available for experimental/custom base images:

```text
Portable Profile → KIWI recipe → Calamares → Generic Live ISO
```

This mode is no longer the preferred path when the user wants the resulting system to remain genuinely Pardus/Fedora/etc.

## Capture and profile rules

- Active-only appearance capture remains the default, but the visible user-installed appearance library is preserved as part of System Settings fidelity.
- `verify` validates payload integrity and required appearance dependencies.
- Source-home paths remain normalized to `{{HOME}}`.
- Known credential stores and likely secrets remain excluded/redacted.
- Application identity retains provider (`apt`, `dnf`, `pacman`, `flatpak`, etc.) rather than pretending package names are universally portable.

## Native remaster boundary

The native adapter operates on the user's supplied ISO rather than reconstructing the distro from another base. For Pardus 25 this means preserving the official GRUB/ISOLINUX tree, `pardus-installer`, APT identity and `/live/filesystem.squashfs`, while changing the live filesystem contents.

## Launcher resolution in Native Mode

Capture may carry Generic Mode compatibility translations, but it also stores the source `Exec=` contract in reversible Suret metadata. The Native adapter removes that metadata and restores same-distro commands. Only browser/web launchers and explicitly mapped third-party vendor applications remain portable fallbacks. This keeps Pardus-native tools native while avoiding broken third-party favorites when the official ISO does not contain a user's external APT repository.

v0.5.5 also treats Native acceptance safety guards as fail-closed predicates rather than command-status chains: safe non-overlapping layouts explicitly return success under Bash `set -e`, while unsafe overlaps exit with code 2. Acceptance scripts emit stage markers before long-running operations for deterministic fault localization.

## Native browser-bound web apps (v0.6.1)

Generic capture may normalize known web apps to `xdg-open URL` for portability,
but the original launcher command is retained in reversible Suret metadata.
Native staging consumes that metadata before generic launcher restoration. For
Brave-owned web apps it preserves only the non-sensitive browser identity and
URL, then renders a profile-independent `brave-browser --app=URL` launcher. The
source browser profile, cookies, history, authentication data and app registry
are deliberately not copied. If Brave was native, its official Debian channel
is installed through a code-owned resolver; if Brave was actually Flatpak, that
provider identity is retained.

