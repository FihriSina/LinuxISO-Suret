# Linux ISO - Suret

**linux-iso** captures a personalized Linux desktop and turns it into a reproducible installation profile and, later in the pipeline, an installable ISO. The visible product name is **Linux ISO - Suret**; repository, Python package and CLI remain `linux-iso`.

> **Project principle:** distribute the Linux experience the user built, not the source disk image.

## Current milestone: v0.2.8

The current implementation targets **KDE Plasma** and contains the capture, verification, restore, application-catalog and experimental ISO-project generation layers.

### v0.2.8: active-only capture + verification + inherited icon fallback handling

Unresolved inherited icon compatibility themes (for example `AdwaitaLegacy`) are now reported as verification warnings instead of fatal errors. Directly active themes still fail verification when unresolved.

- default capture mode is now `active`: installed-but-unused theme collections are not copied wholesale
- `--asset-mode all` retains the old diagnostic/full user-asset capture behavior
- active icon theme inheritance (`Inherits=`) is followed so required base icon themes remain portable
- referenced user-local Plasma widgets are bundled; unused local plasmoids are omitted in active mode
- active KDE icon, cursor, Plasma, color, splash, Aurorae window-decoration, GTK and Kvantum components are resolved separately
- user fonts, custom `.desktop` launchers, user KWin scripts/effects/tabbox assets and local `hicolor` overrides remain captured because they are part of the user workflow or are not safely reducible yet
- directly referenced custom SVG/PNG/JPG/font/sound assets remain captured even when they live outside managed theme trees
- referenced wallpaper packages are promoted to their complete local wallpaper bundle when necessary
- `linux-iso verify` validates manifest payload presence, SHA-256 checksums, bundled components/widgets and appearance-package dependencies
- `stage-iso` refuses to stage a profile with verification errors
- branding is now **Linux ISO - Suret**, fully ASCII-safe for filenames, package metadata and ISO tooling

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
- user KWin scripts/effects/tabbox assets
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

## 5. Stage the experimental ISO build project

First recipe: **Ubuntu 26.04 LTS + KDE Plasma/Kubuntu + Calamares**.

```bash
uv run linux-iso stage-iso ~/linux-iso-profile -o ~/linux-iso-build
```

`stage-iso` runs profile verification first. If verification fails, ISO staging stops instead of embedding a known-broken profile.

The staged tree includes KIWI config, profile payload, Calamares modules and first-boot retry logic. On a KIWI NG build host:

```bash
cd ~/linux-iso-build
./build.sh
```

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

| Area | v0.2.8 |
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
| QEMU boot/install validation | Pending |
| GNOME/Cinnamon/XFCE | Not yet |
| Arch/Fedora/openSUSE image recipes | Not yet |

Cross-family native package translation is intentionally blocked. A Pacman profile is not silently translated into an APT ISO until an explicit mapping layer exists.

## Next acceptance target

A source Plasma desktop with customized panels, third-party plasmoids, manually downloaded icons, a custom wallpaper, cursor/theme/font set, KWin additions and a styled terminal must install into a clean VM without manual desktop reconstruction. Optional applications should appear only when selected during installation.

## Development environment diagnostics (v0.2.8)

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
