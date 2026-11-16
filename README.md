# Linux ISO — Nakş

**linux-iso** captures a personalized Linux desktop and turns it into a reproducible installation profile. The product name **Nakş** reflects the core idea: carry the user's visual and workflow “imprint” to another machine instead of cloning hardware-specific system state.

> **Project principle:** distribute the Linux experience the user built, not the source disk image.

## Current milestone: v0.2

The current implementation targets **KDE Plasma** and already contains the capture, profile, installer-catalog and ISO-project generation layers.

### Captured into the profile

- Plasma panel and widget layout (`plasma-org.kde.plasma.desktop-appletsrc`)
- KDE global appearance, KWin, shortcuts, input, lock screen and Dolphin settings
- Konsole profiles and common terminal configuration
- Zsh/Fish/Bash configuration, Starship, Kitty, Alacritty, WezTerm, Ghostty, Foot and Terminator config paths when present
- user-local Plasma widgets (plasmoids)
- Plasma/KWin scripts, effects, decorations and layout assets
- icon themes, cursors, wallpapers, fonts, themes and color schemes
- `.desktop` launcher overrides
- one-off SVG/PNG/JPG/font/sound assets directly referenced from captured configuration
- system-wide Plasma widgets: package-owned widgets become required package dependencies; unpackaged widgets are bundled into the portable profile

### Applications

Applications are **not embedded into the ISO by default**. The profile records their package provider and the installer generates category-based application selection pages.

- APT and Flatpak selections are installed online into the target system during the Calamares install when possible.
- Flatpak remote name **and URL** are preserved so a clean target can recreate the source remote.
- Snap, unsupported providers, and failed online installs are stored for a first-boot retry.
- Native packages that look like system/manual packages are retained in the manifest but hidden from the normal application chooser.
- packages/components required for appearance are not optional.

### Safety model

The shareable profile intentionally avoids known credential stores such as SSH private keys, GPG private data, keyrings and NetworkManager secrets. Shell-like files are scanned for likely `TOKEN`, `PASSWORD`, `SECRET`, `API_KEY` and similar assignments and those lines are redacted. Browser profiles and personal documents are not part of the capture set.

This is defense-in-depth, not a formal secret-leak proof. Use `linux-iso audit` before publishing a profile or ISO.

## Install for development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 1. Capture the current KDE Plasma system

```bash
linux-iso scan -o ~/linux-iso-profile
```

The resulting portable profile has this shape:

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

Source-home references such as `/home/taha/Pictures/icon.svg` are rewritten to `{{HOME}}/Pictures/icon.svg`. On the target machine the placeholder is resolved to the newly-created user's home directory.

## 2. Inspect and audit

```bash
linux-iso inspect ~/linux-iso-profile
linux-iso audit ~/linux-iso-profile
```

`audit` reports captured custom assets, widget origins, appearance dependencies, selectable applications, filtered native packages and security exclusions.

## 3. Test a profile restore without an ISO

Dry run:

```bash
linux-iso restore ~/linux-iso-profile --target-home /home/testuser
```

Apply:

```bash
linux-iso restore ~/linux-iso-profile --target-home /home/testuser --apply
```

## 4. Generate the categorized application catalog

```bash
linux-iso catalog ~/linux-iso-profile -o application-catalog.json
```

Current categories are Internet, Communication, Office, Multimedia, Development, Gaming, System Tools and Other Applications.

## 5. Stage the first ISO build project

The first concrete recipe is **Ubuntu 26.04 LTS + KDE Plasma/Kubuntu + Calamares**:

```bash
linux-iso stage-iso ~/linux-iso-profile -o ~/linux-iso-build
```

This produces a KIWI NG project containing:

```text
linux-iso-build/
├── config.xml
├── config.sh
├── build.sh
└── root/
    ├── usr/share/linux-iso/profile/
    ├── usr/share/linux-iso/calamares/modules/linuxiso-install/
    ├── etc/calamares/modules/packagechooser-*.conf
    └── etc/systemd/system/linux-iso-firstboot.service
```

On a KIWI NG build host:

```bash
cd ~/linux-iso-build
./build.sh
```

The current repository stages a complete build description, but **v0.2 is still experimental until the generated ISO is built and boot/install-tested in QEMU/KVM**. Do not write an unvalidated image to production machines.

## Installer behavior

The intended install flow is:

```text
Clean base system
      │
      ├─ create target user
      ├─ apply Nakş profile
      │    ├─ Plasma panels/widgets
      │    ├─ themes/icons/cursors/fonts
      │    ├─ custom SVG/PNG assets
      │    └─ terminal configuration
      │
      ├─ category application pages
      │    ├─ Internet
      │    ├─ Multimedia
      │    ├─ Development
      │    └─ ...
      │
      ├─ install selected APT/Flatpak apps online
      └─ retry deferred/failed installs on first boot
```

## Supported scope

| Area | v0.2 |
|---|---|
| KDE Plasma capture | Yes |
| custom SVG/PNG referenced from user config | Yes |
| local Plasma widgets | Yes |
| package-owned system Plasma widget dependency detection | Yes |
| terminal configuration | Yes |
| APT inventory | Yes |
| Flatpak inventory + remote URL | Yes |
| Snap inventory | Yes |
| category application selection generation | Yes |
| KIWI Ubuntu 26.04 KDE recipe | Experimental |
| Calamares integration generation | Experimental |
| QEMU boot/install validation | Pending |
| GNOME/Cinnamon/XFCE | Not yet |
| Arch/Fedora/openSUSE image recipes | Not yet |

Cross-family native package translation is intentionally blocked for now. For example, an Arch/Pacman profile is not silently converted into an Ubuntu/APT ISO; that needs an explicit package-mapping layer in a later milestone.

## Next acceptance target

A source Plasma desktop with two custom panels, third-party plasmoids, manually downloaded launcher/widget icons, a custom wallpaper, cursor/theme/font set, KWin additions and a styled terminal should install into a clean VM without manually recreating the desktop. Optional applications should only appear if selected in the installer.
