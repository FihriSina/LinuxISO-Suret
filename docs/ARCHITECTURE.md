# Linux ISO - Suret architecture

Linux ISO separates **personalization state** from **hardware/system identity**.

## Pipeline

```text
Running KDE Plasma system
          │
          ▼
      Capture Core
          │
   ┌──────┼────────────┐
   ▼      ▼            ▼
 KDE    Package      Security
Adapter Inventory    Sanitizer
   │      │            │
   └──────┼────────────┘
          ▼
  Portable Profile
 manifest + payload
          │
          ├── verify
          ▼
  Distro Build Adapter
          │
   ┌──────┴─────────┐
   ▼                ▼
 KIWI NG          Calamares
          │
          ▼
      Live ISO
```

## Active-only capture

The canonical v0.2.5 profile defaults to `asset_mode=active`. Installed-but-unused theme collections are not copied automatically. Active component directories are copied whole, while direct one-off asset references are copied individually.

The active graph currently includes:

- referenced Plasma widgets;
- active KDE/Plasma appearance components;
- transitive icon-theme inheritance;
- user fonts and launcher overrides;
- KWin scripts/effects/tabbox user state;
- local hicolor overrides;
- direct SVG/PNG/JPG/font/sound references;
- complete wallpaper bundles when a referenced file belongs to a local wallpaper package.

`--asset-mode all` preserves the earlier broad capture behavior for diagnostics.

## Verification boundary

`linux-iso verify` validates that every manifest payload file exists and matches its SHA-256, bundled components/widgets have payload content, and package-owned appearance dependencies are marked required. Missing global Look-and-Feel meta packages are warnings when subcomponents are captured; unresolved active components/widgets are errors.

ISO staging calls verification before generating a KIWI project.

## Portable profile

All source-home paths are normalized to `{{HOME}}`. The profile does not contain a raw copy of `/`, hardware IDs, filesystem UUIDs or known credential stores.

## Application inventory

APT/Pacman/DNF/Zypper identity is retained rather than pretending package names are portable across distro families. Flatpak remotes and Snap install options are preserved. System packages remain in inventory but are hidden from the optional app chooser unless they are user-facing or appearance-required.

## Security

Known credential locations are excluded, likely shell secrets are redacted and very large files are excluded. A later public-export workflow should add a second secret scan over the final staged profile.
