# Linux ISO - Suret

**linux-iso** captures a personalized Linux desktop and turns it into a reproducible installation profile and, later in the pipeline, an installable ISO. The visible product name is **Linux ISO - Suret**; repository, Python package and CLI remain `linux-iso`.

> **Project principle:** distribute the Linux experience the user built, not the source disk image.

## Current milestone: v0.3.10

Ubuntu 26.04 live ISO recipes now include `kiwi-dracut-live`, the KIWI dracut module required by the `iso` + `overlay` image type.

## Safe build on Plasma/Wayland

For the first ISO build on the same machine that is running Plasma, use:

```bash
./scripts/safe-first-iso.sh "$HOME/linux-iso-profile" "$HOME/linux-iso-build"
```

This temporarily inhibits KDE screen locking for the duration of the build, releases the inhibitor automatically on exit, and never changes persistent lock-screen settings. QEMU is not started automatically.


The current implementation targets **KDE Plasma** and contains the capture, verification, restore, application-catalog and experimental ISO-project generation layers.

### v0.3.10: first bootable-ISO build pipeline

The profile scanner is frozen for the first ISO cycle. v0.3.10 moves the project into image-building and live-session validation.

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

| Area | v0.3.10 |
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
| QEMU boot/install validation | Pending real-system run |
| GNOME/Cinnamon/XFCE | Not yet |
| Arch/Fedora/openSUSE image recipes | Not yet |

Cross-family native package translation is intentionally blocked. A Pacman profile is not silently translated into an APT ISO until an explicit mapping layer exists.

## Next acceptance target

A source Plasma desktop with customized panels, third-party plasmoids, manually downloaded icons, a custom wallpaper, cursor/theme/font set, KWin additions and a styled terminal must install into a clean VM without manual desktop reconstruction. Optional applications should appear only when selected during installation.

## Development environment diagnostics (v0.3.10)

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
