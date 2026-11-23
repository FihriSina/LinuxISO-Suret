# Linux ISO - Suret

**linux-iso** captures a personalized Linux desktop and turns it into a reproducible installation profile and, later in the pipeline, an installable ISO. The visible product name is **Linux ISO - Suret**; repository, Python package and CLI remain `linux-iso`.

> **Project principle:** distribute the Linux experience the user built, not the source disk image.

## Native ISO Mode (recommended)

Suret v0.6.0 can remaster a user-supplied distro ISO instead of rebuilding the desktop on an Ubuntu/Kubuntu base. Pardus 25 live ISOs are the first build-capable adapter.

```bash
uv run linux-iso probe-iso ~/Downloads/Pardus-25.2-XFCE-amd64.iso
./scripts/native-acceptance.sh ~/Downloads/Pardus-25.2-XFCE-amd64.iso
```

For a build-only/host-tool retry after a profile was already captured successfully:

```bash
./scripts/retry-native-acceptance.sh ~/Downloads/Pardus-25.2-XFCE-amd64.iso
```

This preserves the existing verified profile and rebuilds only the native ISO path.

A KDE profile on a Pardus XFCE ISO installs KDE inside Pardus, embeds the captured profile, installs source applications when resolvable, preserves the Pardus bootloader/installer/repositories, and repacks the ISO. Generic KIWI mode remains available through `stage-iso` / `build-iso`.


## Current milestone: v0.6.0

### v0.6.0: Android Studio vendor-archive resolver + extra-data escape hatch

- Moves a genuinely captured `com.google.AndroidStudio` Flatpak out of the Pardus 25 Flatpak 1.16.5 `extra-data/apply_extra` path that fails on `/proc/self/fd/N`.
- Resolves Android Studio only through a compiled Suret allow-list, downloads the official Linux archive from Google-owned hosts, pairs it with the SHA-256 published on Android Developers, and verifies the hash before extraction.
- Extracts only an `android-studio/` tree; absolute/traversal paths, escaping links, device/FIFO entries, and setuid/setgid archive modes are rejected.
- Installs the IDE under `/opt/android-studio`, creates a real `com.google.AndroidStudio.desktop`, and rewrites only the matching captured Flatpak launcher; unrelated `TryExec=flatpak` entries are untouched.
- Uses disk-backed `/var/tmp/linux-iso-vendor` for the ~GB vendor archive instead of the chroot `/run` tmpfs, and removes the temporary download after successful installation.
- If Android Studio was the only genuine Flatpak, the rendered Native plan contains no Flatpak apps and the Flatpak/bubblewrap runtime path is skipped entirely.
- Current regression suite: 228 tests.

### v0.5.9: Vendor-native Code/Signal resolution + conditional Flatpak

- Keeps captured APT applications on an APT-native path when Suret has a vetted official vendor resolver: VS Code uses Microsoft's official repository and Signal Desktop uses Signal's official repository.
- Restores the captured native `Exec=` command for those launchers instead of leaving a `flatpak run ...` translation after the vendor-native package is installed.
- Vendor repository metadata is a compiled Suret allow-list; profile data cannot inject arbitrary repositories, keys or package names. No Debian/Ubuntu/PPA repository is mixed into Pardus.
- True Flatpak captures remain Flatpak, but Flatpak/bubblewrap are now installed only when the profile actually requires them.
- Logs Flatpak/bubblewrap versions and diagnoses the upstream Flatpak 1.16.5 `/proc/self/fd` regression without pulling a foreign-distro package to fix it.
- Retains v0.5.8 GPU isolation and fail-closed Flatpak deployment gates for genuine Flatpak applications.
- Current regression suite: 220 tests.

### v0.5.8: Flatpak extra-data sandbox + host-hardware isolation

- Makes the Native chroot root a real self bind-mount so bubblewrap can change recursive mount propagation instead of failing with `Failed to make / slave: Invalid argument`.
- Supports Flatpak `extra-data` installers when Pardus blocks unprivileged user namespaces by using bubblewrap's setuid fallback only inside a sealed `root:root 0700` disposable work window; the privilege bit is removed before the work tree is exposed or the ISO is repacked.
- Forces build-time locale to `C.UTF-8`, eliminating inherited `tr_TR`/`en_US` locale warnings without changing the captured target-user locale.
- Forces `FLATPAK_GL_DRIVERS=default` and masks host `/proc/modules` + `/sys/module` during the chroot package phase so host NVIDIA/AMD driver state cannot select target Flatpak runtime extensions.
- Adds fail-closed gates for undeployed required Flatpak apps and host-specific GPU runtimes.
- Current regression suite: 213 tests.

### v0.5.7: Root-owned Native retry cleanup

- Recovers automatically from root-owned `unsquashfs`/chroot work trees left by failed Native builds.
- Detaches stale `run/sys/proc/dev` mounts before privileged cleanup and uses `rm --one-file-system` to prevent crossing mount boundaries.
- Adds a user-owned Suret staging marker for safe privileged cleanup of custom Native build paths; the default build path remains recoverable for pre-marker releases.
- Direct generated-build reruns use the same mount-safe work reset.
- Current regression suite: 206 tests.

### v0.5.6: Native APT media isolation

- Fixes Pardus 25.2 Native `apt-get update` exit 100 caused by the live-only `file:/run/live/medium` repository inside the chroot.
- Uses an isolated build-only APT source list and package-index state under `/run/linux-iso/apt-build`; the ISO's original live/installer APT configuration is preserved byte-for-byte.
- Uses only official Pardus 25 `yirmibes`, `yirmibes-deb`, and security repositories during Native package installation.
- Disables build-time translation/Contents indexes to reduce unnecessary metadata traffic.
- All APT availability checks and installs share the same isolated source configuration.
- Current regression suite: 200 tests.

### v0.5.5: Native acceptance guard fix

- Fixes a `set -e` interaction that made valid Native acceptance/retry layouts exit silently immediately after the `Result:` line.
- Rewrites Native path-overlap guards as explicit conditionals and returns success explicitly for safe layouts.
- Adds visible phase markers around each long Native acceptance stage for deterministic failure localization.
- Keeps all v0.5.4 deep-hardening behavior intact.
- Current regression suite: 196 tests.

### v0.5.4: Native deep hardening

- Makes source appearance packages mandatory Native install dependencies instead of silently skipping them.
- Applies the captured profile to one primary local account only, with volatile live-user state and fingerprinted convergence markers.
- Hardens profile/capture safety against symlink traversal, special files, credential-store paths, generic text secrets, and credential-bearing launcher commands.
- Adds generated-template gates, complete host helper checks, post-install disk-space modeling, destructive path-overlap guards, automatic successful-work cleanup, and relocatable ISO SHA-256 output.
- QEMU now opens the exact expected Native ISO and validates its checksum before boot.
- Keeps v0.5.3 xorriso 1.5.6 selective mapping and v0.5.2 chroot/boot/profile gates intact.
- Current regression suite: 192 tests.

### v0.5.3: Native xorriso/PATH compatibility + remaster hardening

- Normalizes system sbin paths before dependency probing and generated Native builds, fixing false `chroot`-missing reports when `/usr/sbin` is absent from a desktop user's PATH.
- Uses xorriso-native `-find ... -exec echo --` traversal rather than shell-find `-print`, matching the xorriso 1.5.6 shipped on the tested Pardus host.
- Avoids xorriso 1.5.6's known boot replay failure by no longer remapping the complete extracted ISO tree. Only the rebuilt squashfs and changed live metadata are mapped back; boot-image files remain authoritative from the loaded base ISO.
- Retains the v0.5.2 hardening: isolated chroot `/run`, `policy-rc.d`, required KDE/SDDM gates, pre-SDDM profile convergence, refreshed live metadata, compatible OVMF pairing, and source/base architecture + Pardus major-release checks.
- Keeps Pardus 25 official repository identity intact; no cross-distro repositories are introduced.
- Current regression suite: 168 tests.


### v0.5.1: Native host dependency bootstrap

- Native acceptance checks and installs the complete host remaster/QEMU toolchain before probing the supplied ISO.
- On Pardus/other apt-based hosts this includes `xorriso`, `squashfs-tools`, `rsync`, QEMU utilities and OVMF when missing.
- Prevents one-missing-tool-at-a-time failures such as the initial `xorriso` blocker.


### v0.4.3: deterministic Ubuntu archive trust anchor

- Bundles the Ubuntu Archive Automatic Signing Key (2018) used by Ubuntu 26.04.
- KIWI repository signing keys now use a local `this://keys/...` URI instead of downloading the key at build time.
- Keeps APT signature verification enabled; this is not an insecure/trusted-repository bypass.
- Adds `ubuntu-keyring` to bootstrap so the installed image carries the standard Ubuntu archive keyring too.
- Final acceptance no longer depends on `archive.ubuntu.com/.../ubuntu-archive-keyring.gpg` returning HTTP 200.
- Adds `scripts/retry-acceptance.sh` to reuse an already-valid v10 profile after a build-only failure, avoiding another full desktop scan.

### v0.4.2: batch runtime compatibility and source-state repair

- Treats the wallpaper shown on the current Plasma activity and screen 0 as authoritative; dormant activities no longer win capture ordering.
- Uses a safe Breeze SDDM runtime shell with the captured source wallpaper/avatar, while archiving the source SDDM theme instead of activating potentially incompatible source QML on the Ubuntu/Plasma target.
- Rewrites source-only Pardus launchers to working target equivalents (Dolphin filesystem view, Info Center, Discover, PowerDevil settings).
- Rewrites VS Code, Signal and Steam launchers/providers to portable Flathub identities when their source distro packages are not portable to the target.
- Normalizes ChatGPT and WhatsApp Web launchers to `xdg-open` URLs, avoiding browser-profile-specific source commands.
- Resolves pinned/favorite launchers from Flatpak and Snap export directories, so applications such as Android Studio remain visible in restored Kickoff favorites.
- Adds the target runtime dependencies needed by those portable launcher mappings.
- Fidelity schema v10 forces a fresh source scan so stale launcher and wallpaper state cannot leak from earlier profiles.
- Project regression suite: 138 tests.

If any runtime issue remains after the installed-system boot, run `suret-diagnose` once and send the generated archive; it is designed for batch diagnosis rather than one-error-per-build debugging.

### v0.4.0: final acceptance / one-window install convergence

- Adds `scripts/final-acceptance.sh` as the single end-to-end acceptance command: fresh scan, verify, audit, portability, ISO build, then QEMU installer launch.
- QEMU now defaults to `install` mode, creates a clean test disk, boots the ISO only once, and after Calamares Restart automatically continues from the installed disk in the same QEMU process.
- Persists a per-test OVMF VARS image so UEFI boot entries survive installer reboot and later installed-system replay.
- Adds a first-login KDE convergence hook that refreshes application/icon caches and reapplies the captured visible wallpaper after Plasma/DBus is live, preventing target-distro wallpaper fallback.
- Records the final portable visible-wallpaper path in fidelity schema v10 and verifies the asset before ISO staging.
- Optional APT applications install independently so one unavailable source-distro package does not block all other selected packages.
- Retains v0.3.20-v0.3.33 Calamares, initramfs, automirror, cleanup, desktop-surface, source branding, GRUB, SDDM, avatar, KIO, launcher and schema-gate fixes.
- Project regression suite: 127 tests.

For the final acceptance cycle on the source desktop, run only:

```bash
./scripts/final-acceptance.sh
```

The QEMU window is intentionally kept alive across installer reboot. After clicking **Done / Restart** in Calamares, do not close QEMU; the same VM should boot the installed disk automatically.


### v0.3.33: safe-build profile schema gate fix

- `safe-first-iso.sh` now accepts the current fidelity schema (`>= 8`) instead of incorrectly requiring exactly schema 7.
- Missing/old profile manifests fail with an explicit detected schema message before the ISO build starts.
- Regression coverage executes the real shell gate for schema 7, 8, future schema values, and missing manifests.

### v0.3.32: system-visible fidelity (GRUB, SDDM, avatar, KIO compatibility)

- Captures and reapplies the active source GRUB theme/background and presentation settings without copying host-specific boot entries.
- Captures and reapplies the active SDDM theme; the captured user avatar is also registered with AccountsService.
- Adds `kio-extras` so the portable `Bilgisayar` launcher can open KDE's `computer:/` location.
- Creates the target user's portable `~/.local/bin/env` shim so captured shell startup files do not fail on a fresh account.
- Fidelity schema is now v8; re-scan the source desktop before building.

### v0.3.31: XDG-aware desktop installer launcher

- Masks Kubuntu/OEM installer desktop entries so the live Kickoff/KRunner shows only the Suret source-branded installer.
- Uses the captured source distribution name for the live user's visible identity (for example `Pardus Live`).
- Installs a single source-branded installer application entry (`Pardus'u Kur` in Turkish for a Pardus source profile).
- Marks QEMU windows as `Suret - LIVE ISO` or `Suret - INSTALLED SYSTEM`.
- Rewrites the Pardus-only `pardus-mycomputer` desktop action to the portable KDE `dolphin computer:/` equivalent while preserving the visible `Bilgisayar` launcher.

### v0.3.29: desktop-surface capture + sharp installer icons + live wallpaper truth

- Captures the localized XDG desktop surface (`Desktop`, `Masaüstü`, etc.) as UI state, including visible launcher/link files but not arbitrary personal documents.
- Captures `.desktop` launchers referenced by Plasma icon applets even when they live under source-distro system paths, then rewrites those references to portable user-local copies.
- Preserves `user-dirs.dirs` / locale metadata so restored desktop items appear in the correct localized directory.
- Verifies visible desktop launchers before ISO staging, reducing QEMU-only discovery of missing desktop icons.
- Installer application cards select the highest-quality captured icon (SVG/SVGZ first, then largest PNG) and render icons at a controlled size with mipmapping rather than stretching tiny raster icons across the card.
- When a live Plasma session is available, the scanner queries the supported Plasma scripting API through D-Bus and records the wallpaper actually shown on screen, overriding stale persisted `Next`/vendor wallpaper values.
- Adds fidelity schema v7; re-scan the source desktop before building.

### v0.3.28: source-native installer branding + visual application cards

- Captures source-distribution identity metadata from `/etc/os-release` (name, version, logo token, colors and support URLs) and snapshots an available distro logo into the profile.
- Generates a dedicated `linuxiso-source` Calamares branding component from the captured source identity instead of reusing Kubuntu branding. Pardus profiles therefore present Pardus product naming/colors/logo; other source distributions receive their own identity palette.
- Uses the captured active wallpaper in the Calamares installation slideshow when available.
- Slideshow-based source desktops are pinned to the source-visible image in the restored snapshot so Plasma cannot replace the first boot with the target distro default wallpaper; the full wallpaper collection remains captured.
- Replaces the v0.3.27 netinstall tree with dynamically generated `packagechooserq` pages: one QML file per category, never a shared static LibreOffice page.
- Every optional application remains selected by default; users opt out by unchecking cards.
- Application choices are rendered as visual cards with name, provider, description and either a captured real application icon or an offline-generated branded fallback cover.
- The live desktop launcher uses the captured source distribution name (`Install Pardus`, `Install Fedora`, etc.).
- Adds fidelity schema v6; source branding requires a fresh scan.

### v0.3.27: visible desktop state + opt-out application selection

- v0.3.27 introduced opt-out selection through checkbox-based netinstall pages; v0.3.28 supersedes those pages with source-branded visual card pages while preserving the same selected-by-default behavior.
- Captures Kickoff favorite membership from the KActivities `ResourceLink` database and exact favorite ordering from `kactivitymanagerd-statsrc`.
- Sanitizes the captured KActivities database so only application-favorite links and schema metadata remain; activity/resource usage history is not copied.
- Captures the source user's avatar and additional user-visible KDE state such as KWin rules, KRunner settings, locale, power-management settings and System Settings state.
- Captures `.desktop` launchers referenced by Kickoff favorites in addition to task-manager pins.
- For slideshow wallpapers, uses the most recently accessed source slide as the initial restored image.
- Fidelity schema v5 is superseded by v6.

### v0.3.26: moved-wallpaper reference repair

- Adds a mandatory Calamares target-profile shellprocess immediately after target-user creation; visual restore no longer depends on the optional application-install Python job being inserted correctly.
- Runtime Calamares auditing now refuses to start if the target-profile job or application job is missing or ordered incorrectly.
- Captures `.desktop` files referenced by Plasma pinned launchers so restored panels do not degrade to generic document icons on Ubuntu/Kubuntu.
- Captures wallpaper directory references as well as individual image files and rewrites them to portable user-local paths; verification rejects unresolved absolute wallpaper paths instead of allowing a silent Kubuntu fallback.
- Adds fidelity schema v3; re-scan the Pardus source desktop before rebuilding.
- `test-qemu.sh RESULT installed` boots the existing QCOW2 directly without attaching the ISO.

### v0.3.24: strict desktop-fidelity capture and restore

- Bundles the exact active KDE appearance components even when they are package-owned on Pardus, so Ubuntu/Kubuntu theme versions cannot silently replace the source icon/cursor/Plasma/color/decoration assets.
- Captures wallpapers and other referenced local assets outside the source home (including system wallpaper paths), relocates them into portable user-local storage, and rewrites configuration references.
- Clears Kubuntu skeleton/vendor personalization from the live and installed user before applying the Suret profile, removing leftover `HOW-TO Guides`, `Kubuntu Website`, vendor panel state and similar defaults.
- Writes profile-application markers for live/installed verification and replaces visible Calamares `Kubuntu` text with `Linux ISO - Suret`.
- Adds fidelity schema v2 to newly captured profiles; v0.3.25 supersedes this with schema v3 for launcher and wallpaper-directory capture.
- Real QEMU validation has now completed the full install chain and booted successfully from the installed QCOW2 disk; the active gate is visual fidelity.

### v0.3.23: KIWI-safe Calamares install-chain hardening

- Replaces Ubuntu/Kubuntu's distro cleanup `packages` job with an offline-safe Suret target finalizer, avoiding package-manager failures during installation.
- Removes the duplicate Kubuntu `pkgselect` Customize page and its `pkgselectprocess`, snap-selection, `add386arch`, `rmcdrom`, and installer-log jobs while preserving Suret's own categorized `packagechooser` application pages.
- Cleans live-only SDDM autologin, passwordless sudo, the `live` account, CD-ROM APT entries, and installer launchers from the installed target without `apt-get` or `dpkg`.
- Records the actual target username so live-user cleanup cannot remove the installed user accidentally.
- Adds a runtime safety audit that refuses to launch Calamares if known Ubuntu live-ISO-only jobs survive the patch.
- Keeps the v0.3.20 kernel-copy, v0.3.21 initramfs, and v0.3.22 automirror fixes intact.


### v0.3.22: Ubuntu 26.04 Calamares automirror compatibility

- Preserves Ubuntu/Kubuntu's `automirror` job and its mirror/global-storage behavior.
- Inserts a Suret compatibility shellprocess immediately before `automirror`.
- Creates `/etc/apt/sources.list` only when it is absent so Ubuntu's automirror can remove the legacy file safely after writing modern `/etc/apt/sources.list.d/ubuntu.sources`.
- Does not overwrite an existing legacy sources file and keeps the v0.3.20 kernel-copy and v0.3.21 initramfs fixes intact.


### v0.3.21: Ubuntu 26.04 initramfs compatibility

- Replaces Calamares' built-in Debian `initramfs` job with a Suret-owned target-chroot shellprocess.
- Avoids Calamares' hard-coded `update-initramfs -c -t`, because Ubuntu 26.04 `initramfs-tools` 0.151 no longer accepts `-t`.
- Creates missing target initramfs images and updates existing ones per installed kernel version without reintroducing Casper assumptions.
- Keeps the v0.3.20 kernel-copy/runtime sequence hardening unchanged.


### v0.3.20: Calamares runtime sequence hardening

- Replaces the actual Kubuntu Calamares job instance `shellprocess@before_bootloader_kerncopy` with a Linux ISO - Suret-owned shellprocess instance.
- Removes the distro-specific `contextualprocess@before_bootloader` job because the KIWI rootfs already carries the required bootloader packages.
- Rewrites any remaining `/cdrom/casper/vmlinuz` and Casper squashfs references immediately before Calamares starts.
- Launches Calamares directly after the Suret runtime patch so the Kubuntu launcher cannot restore distro-specific Casper assumptions.
- Keeps a fallback kernel-copy config for older Calamares sequence layouts.

### v0.3.19: KIWI kernel handoff for Calamares

- Replaces Kubuntu Calamares' hard-coded `/cdrom/casper/vmlinuz` copy step with the KIWI live kernel at `/cdrom/boot/x86_64/loader/linux`.
- Neutralizes the Ubuntu `apt-cdrom` bootloader context, because the KIWI ISO is not a Casper/Apt CD repository.
- Adds `grub2-common` and `efibootmgr` explicitly for deterministic target bootloader installation.
- Keeps the v0.3.18 `rsync` and v0.3.17 `LiveOS/squashfs.img` fixes.

### v0.3.18: Calamares rsync runtime fix

- Adds `rsync` explicitly to the live ISO image.
- Fixes Calamares `unpackfs` failure `rsync failed with error code 127`.
- Keeps the v0.3.17 KIWI `LiveOS/squashfs.img` media-path fix and live-session safeguards.

### v0.3.17: Installer media-path and live-session fixes

- Dynamic application categories now use Calamares `packagechooser`; `packagechooserq` was showing Kubuntu's hard-coded LibreOffice QML on every injected page.
- `dosfstools`, `e2fsprogs`, and `parted` are explicit live-image dependencies so Calamares can create FAT32 EFI and ext filesystems reliably.
- `test-qemu.sh` now creates a persistent 40 GiB QCOW2 installer disk and user-mode network automatically.
- Live hostname resolution and the captured `~/.local/bin/env` shell hook are made quiet for testing.


Ubuntu 26.04 live ISO recipes now include `kiwi-dracut-live`, the KIWI dracut module required by the `iso` + `overlay` image type.

## Safe build on Plasma/Wayland

For the first ISO build on the same machine that is running Plasma, use:

```bash
./scripts/safe-first-iso.sh "$HOME/linux-iso-profile" "$HOME/linux-iso-build"
```

This temporarily inhibits KDE screen locking for the duration of the build, releases the inhibitor automatically on exit, and never changes persistent lock-screen settings. QEMU is not started automatically.


The current implementation targets **KDE Plasma** and contains the capture, verification, restore, application-catalog and experimental ISO-project generation layers.


### v0.3.17: UEFI-first hybrid ISO boot

The ISO recipe now explicitly sets KIWI firmware mode to `efi` and enables a GPT hybrid MBR. On x86_64 this asks KIWI to embed an EFI boot path while preserving BIOS/CSM boot support. The generated QEMU helper boots with OVMF/UEFI by default; legacy BIOS can still be selected with `LINUX_ISO_QEMU_FIRMWARE=bios`. The v0.3.14 Plasma X11 live-session fallback remains in place.

### v0.3.14: BIOS-safe boot and X11 live-session fallback

The profile scanner is frozen for the first ISO cycle. v0.3.14 hardens the first generated ISO after real QEMU validation: BIOS GRUB uses a legacy-safe kernel handoff while UEFI keeps the normal GRUB handoff, and the live SDDM session uses Plasma X11 for broad virtual-GPU compatibility.

- `linux-iso build-doctor` checks Podman, uv, KIWI fallbacks, QEMU, KVM access and free disk space
- Pardus prefers a direct KIWI build inside the official Ubuntu OCI build box through Podman, avoiding the VM/QCOW2 path
- `linux-iso build-iso PROFILE` stages and executes the KIWI build
- generated `build.sh` mounts the staged description and result directories into the official Ubuntu build box and runs `kiwi-ng system build` directly; VM boxbuild and host-direct KIWI remain fallbacks
- direct builds run `kiwi-ng image info --resolve-package-list` before creating the ISO
- the ISO recipe creates an ephemeral `live` user, SDDM autologin and an installer desktop launcher
- the captured Suret profile is applied to the live KDE session as well as to the final Calamares-created user
- generated `build.sh` blocks only system sleep/suspend with `systemd-inhibit`; it does not inhibit desktop idle/lock behavior
- generated `test-qemu.sh` boots the resulting ISO with KVM when available and TCG fallback otherwise
- widget minimum Plasma API is checked against the recipe target (Ubuntu 26.04 recipe currently targets Plasma 6.6)
- the Calamares patch helper no longer imports the development-only `linux_iso` Python package inside the image
- KIWI 11.1.x bootloader selection uses the schema-valid `<bootloader name="grub2"/>` child element inside the ISO `<type>` node

### Existing audit-driven fixes

- Aurorae window decorations and icon themes are grouped as bundles in `audit`
- active Aurorae decoration is detected from `kwinrc`
- a missing global Look-and-Feel meta package is a warning, not a fatal error, when its active subcomponents are captured separately
- native package classification hides runtimes, libraries, microcode, headers and `-dev` packages from the application chooser
- Flatpak/native `.desktop` categories improve application categorization
- Flatpak remote URL and Snap channel/classic metadata are retained

## Captured desktop state

- Plasma panel and widget layout (`plasma-org.kde.plasma.desktop-appletsrc`)
- KDE global appearance, KWin, shortcuts, input, lock screen and Dolphin settings
- Konsole profiles and common terminal configuration
- Zsh/Fish/Bash configuration, Starship, Kitty, Alacritty, WezTerm, Ghostty, Foot, Terminator and Yakuake config paths when present
- referenced user-local Plasma widgets
- active themes, icon themes, cursors, wallpapers, fonts, color schemes and window decorations
- enabled user KWin scripts/effects plus user tabbox assets
- `.desktop` launcher overrides
- one-off SVG/PNG/JPG/font/sound assets referenced by captured configuration
- package-owned system Plasma widgets as required package dependencies

## Applications

Applications are **not embedded into the ISO by default**. The profile records their provider and the installer generates category-based selection pages.

- APT and Flatpak selections are installed online during Calamares when possible.
- Snap or failed/deferred installs can be retried after first boot.
- appearance-required packages are mandatory and are not normal optional choices.
- system/manual packages that are not user-facing applications remain in the manifest but are hidden from the chooser.

## Safety model

Known credential stores such as SSH private keys, GPG private data, keyrings and NetworkManager secrets are excluded. Likely `TOKEN`, `PASSWORD`, `SECRET`, `API_KEY` and similar shell assignments are redacted. Browser profiles and personal documents are outside the default capture graph.

This is defense-in-depth, not a formal secret-leak proof. Run both `audit` and `verify` before publishing a profile or ISO.

## Development with uv

Install uv once:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then:

```bash
uv sync
uv run linux-iso --help
```

No manual `python3 -m venv` or `source .venv/bin/activate` is required.

## 1. Capture the current KDE Plasma system

Recommended active-only profile:

```bash
uv run linux-iso scan -o ~/linux-iso-profile
```

Diagnostic/full user-asset capture:

```bash
uv run linux-iso scan -o ~/linux-iso-profile --asset-mode all
```

The default profile shape is:

```text
linux-iso-profile/
├── manifest.yaml
├── summary.json
└── payload/
    └── home/
        ├── .config/
        ├── .local/
        └── ...
```

Source-home references such as `/home/sina/Pictures/icon.svg` become `{{HOME}}/Pictures/icon.svg` and are resolved to the target user's home on restore.

## 2. Inspect, audit and verify

```bash
uv run linux-iso inspect ~/linux-iso-profile
uv run linux-iso audit ~/linux-iso-profile
uv run linux-iso verify ~/linux-iso-profile
uv run linux-iso portability ~/linux-iso-profile --recipe ubuntu-26.04-kde
```

`verify` checks payload existence and hashes, bundled appearance components, Plasma widgets and required appearance packages. A missing global-theme meta package can be reported as a warning when active subcomponents are already captured; unresolved active components/widgets are errors.

## 3. Test restore without an ISO

Dry run:

```bash
uv run linux-iso restore ~/linux-iso-profile --target-home /home/testuser
```

Apply:

```bash
uv run linux-iso restore ~/linux-iso-profile --target-home /home/testuser --apply
```

## 4. Generate the categorized application catalog

```bash
uv run linux-iso catalog ~/linux-iso-profile -o application-catalog.json
```

## 5. Build the first experimental ISO

First recipe: **Ubuntu 26.04 LTS + KDE Plasma/Kubuntu + Calamares**.

```bash
uv run linux-iso build-doctor
uv run linux-iso stage-iso ~/linux-iso-profile -o ~/linux-iso-build
uv run linux-iso build-iso ~/linux-iso-profile -o ~/linux-iso-build --backend auto
```

`stage-iso` remains available for inspection-only workflows. `build-iso` stages the same project and then prefers the direct Podman container backend, with VM boxbuild/host-direct KIWI as fallbacks according to host tools. The staged project also contains `build.sh` and `test-qemu.sh`.

For the first end-to-end attempt, `./scripts/first-iso.sh` runs tests, verification, portability, host diagnostics and staging; if the host is ready it starts the ISO build automatically.

The build recipe remains **experimental until a generated ISO passes QEMU/KVM live boot and Calamares installation validation**.

## Installer intent

```text
Clean base system
      │
      ├─ create target user
      ├─ apply Suret profile
      │    ├─ Plasma panels/widgets
      │    ├─ active themes/icons/cursors/fonts
      │    ├─ custom SVG/PNG assets
      │    └─ terminal configuration
      │
      ├─ category application pages
      ├─ install selected apps online
      └─ retry deferred installs on first boot
```

## Supported scope

| Area | v0.3.26 |
|---|---|
| KDE Plasma capture | Yes |
| active-only appearance capture | Yes |
| icon theme inheritance | Yes |
| custom SVG/PNG references | Yes |
| referenced local Plasma widgets | Yes |
| package-owned system widget dependency detection | Yes |
| terminal configuration | Yes |
| profile verification/checksums | Yes |
| APT inventory | Yes |
| Flatpak inventory + remote URL | Yes |
| Snap inventory | Yes |
| categorized installer catalog | Yes |
| Ubuntu 26.04 KDE KIWI recipe | Experimental |
| Calamares integration | Experimental |
| Live-user + QEMU helper generation | Yes |
| QEMU boot/install validation | Passed: install + ISO-less installed boot |
| GNOME/Cinnamon/XFCE | Not yet |
| Arch/Fedora/openSUSE image recipes | Not yet |

Cross-family native package translation is intentionally blocked. A Pacman profile is not silently translated into an APT ISO until an explicit mapping layer exists.

## Next acceptance target

A source Plasma desktop with customized panels, third-party plasmoids, manually downloaded icons, a custom wallpaper, cursor/theme/font set, KWin additions and a styled terminal must install into a clean VM without manual desktop reconstruction. Optional applications should appear only when selected during installation.

## Development environment diagnostics (v0.3.26)

`uv` manages the project environment. The project explicitly enables the `dev`
dependency group, which contains pytest.

```bash
uv sync --dev
uv run linux-iso doctor
uv run --dev python -m pytest -q
```

For a reproducible local test command, use:

```bash
./scripts/test.sh
```

The helper clears uv group-suppression flags, explicitly syncs the development dependency group, and runs pytest through `python -m pytest` so testing does not depend on a generated console-entrypoint file. If the project `.venv` becomes stale or partially damaged, run `./scripts/repair-env.sh`.

## Native compatibility note (v0.5.3)

Pardus hosts shipping xorriso 1.5.6 are supported. Suret uses xorriso-native `-find ... -exec echo --` syntax and selectively replaces only remastered live payload files, leaving base ISO boot-image files untouched before boot replay. Native acceptance also normalizes sbin paths so installed tools such as `/usr/sbin/chroot` are detected reliably.
