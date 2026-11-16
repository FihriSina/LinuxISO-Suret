# MyDistro Profile — v0.1 MVP

**Goal:** distribute the *Linux experience* a user has built over time, not just the base distribution.

This first milestone targets **KDE Plasma** and captures the state needed for later ISO generation:

- Plasma panel/widget configuration (`plasma-org.kde.plasma.desktop-appletsrc`)
- KDE global appearance and KWin configuration
- keyboard shortcuts, cursor/input and lock-screen configuration
- Konsole profiles and terminal appearance
- local Plasma widgets (plasmoids)
- local themes, icons, cursors, wallpapers, fonts and color schemes
- user `.desktop` launchers and icon overrides
- one-off SVG/PNG/JPG/font assets referenced directly by captured config files
- manually selected native packages when the package manager exposes them
- Flatpak and Snap application inventories
- category metadata for an installer UI

## Safety model

The MVP intentionally does **not** copy credential stores such as SSH/GPG/keyrings/NetworkManager secrets. Possible `TOKEN`, `PASSWORD`, `SECRET`, `API_KEY`, etc. assignments in `.bashrc`, `.zshrc` and Fish config are redacted. Browser profiles and personal documents are not part of the capture set.

## Install for development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Capture this machine

```bash
mydistro scan -o ./taha-desktop-profile
```

Output:

```text
taha-desktop-profile/
├── manifest.yaml
├── summary.json
└── payload/
    └── home/
        ├── .config/
        └── .local/
```

Any absolute reference to the source user's home directory found in captured text configs is rewritten to `{{HOME}}`. The restore phase resolves that placeholder to the new user's home directory.

## Inspect the result

```bash
mydistro inspect ./taha-desktop-profile
```

## Dry-run a restore

```bash
mydistro restore ./taha-desktop-profile --target-home /home/newuser
```

Actually apply it:

```bash
mydistro restore ./taha-desktop-profile --target-home /home/newuser --apply
```

## Stage for KIWI

```bash
mydistro stage-kiwi ./taha-desktop-profile -o ./kiwi-stage
```

This deliberately only stages the profile overlay in v0.1. A distro-specific KIWI image description and Calamares installer integration belong to the next milestone; pretending a single generic ISO recipe is already safe across Debian/Ubuntu/Arch/Fedora would create a fragile installer.

## Manifest package model

Every discovered application is represented with:

- provider (`apt`, `pacman`, `dnf`, `flatpak`, `snap`)
- installer category (`internet`, `development`, `multimedia`, `gaming`, `communication`, `office`, `system`, `other`)
- `required_for_appearance` hint for packages that appear to participate in the desktop look

That becomes the data source for the future Calamares screen where the ISO user chooses applications category-by-category while appearance dependencies remain selected by default.

## Roadmap

### v0.2 — KDE fidelity
- validate Plasma 6 restore in a disposable VM
- detect system-wide third-party plasmoids and map them back to installable packages
- dependency graph: config/component -> required package
- preview/report custom icon and wallpaper references before export
- preserve file permissions and selected symlinks safely

### v0.3 — Installer
- build a distro-specific Live ISO through KIWI NG
- embed the captured profile in `/usr/share/mydistro/profile`
- Calamares module for category-based online application selection
- first-login service to apply the profile after target user creation

### v0.4+
- GNOME adapter (dconf, extensions, themes)
- Cinnamon/XFCE adapters
- Arch/Fedora/openSUSE package backends
- standalone `.mydistro-profile` import without reinstalling Linux
