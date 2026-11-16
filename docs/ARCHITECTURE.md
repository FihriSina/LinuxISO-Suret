# Linux ISO — Nakş architecture

Linux ISO deliberately separates **personalization state** from **hardware/system identity**.

## Main pipeline

```text
Running KDE Plasma system
          │
          ▼
      Capture Core
          │
   ┌──────┼──────────┐
   ▼      ▼          ▼
 KDE    Package    Security
Adapter Inventory  Sanitizer
   │      │          │
   └──────┼──────────┘
          ▼
  Portable Profile
 manifest.yaml + payload/home
          │
          ▼
  Distro Build Adapter
          │
   ┌──────┴─────────┐
   ▼                ▼
 KIWI NG          Calamares
 recipe           integration
   │                │
   └──────┬─────────┘
          ▼
      Live ISO
```

## 1. Portable profile

The profile is the canonical artifact. It contains the native desktop configuration and all portable assets required to reconstruct the user's experience. It does **not** contain a raw copy of `/`, hardware IDs or disk UUID state.

All source-home paths are normalized to `{{HOME}}`; manifest destinations use the same placeholder. This allows a profile captured from `/home/taha` to be applied to `/home/alper` without path surgery by the user.

## 2. KDE adapter

The KDE adapter captures Plasma and KWin configuration plus user-local data packages. It extracts referenced Plasma plugin IDs from `plasma-org.kde.plasma.desktop-appletsrc`.

For every referenced widget:

1. user-local plasmoid -> bundle it;
2. system widget owned by a distro package -> mark that package `required_for_appearance`;
3. system widget with no package owner -> bundle the widget into the target user's local plasmoid directory;
4. missing widget -> report it in the audit so the profile can be reviewed.

Text configuration and QML/metadata inside captured paths are scanned for direct references to user-owned SVG, PNG, wallpaper, font and sound assets. Referenced files are bundled and their absolute source-home paths become `{{HOME}}/...`.

## 3. Application inventory

The manifest retains package-provider identity:

- APT
- Pacman
- DNF
- Zypper (future full inventory support)
- Flatpak
- Snap

For native packages, `linux-iso` separates **inventory retention** from **installer visibility**. A manual package is shown as an end-user application when it owns a desktop launcher, is a recognized CLI application, belongs to a known app category, or participates in appearance. Other manual/system packages remain in the manifest but do not clutter the chooser.

Flatpak records both its remote name and remote URL. This is necessary because a clean target might not already have the same remote configured.

## 4. Appearance dependency policy

There are two application classes:

- **required for appearance** — included automatically / cannot be deselected;
- **optional application** — presented category-by-category during installation.

A package can become appearance-required through package-name heuristics or an explicit component dependency such as a referenced package-owned Plasma widget.

## 5. Calamares integration

Each non-empty app category becomes a `packagechooserq` instance using `optionalmultiple` + `legacy`. The selection is stored by Calamares in `packagechooser_<instance-id>` GlobalStorage keys.

The generated `linuxiso-install` Python job runs after the target user exists. It:

1. applies `payload/home` to the target user's home;
2. resolves `{{HOME}}` placeholders;
3. fixes ownership;
4. always includes appearance-required items in the install plan;
5. attempts APT and Flatpak installation in the target environment;
6. writes failed/deferred items to `/var/lib/linux-iso/pending-apps.json`.

A systemd oneshot service retries pending APT/Flatpak/Snap work after the installed machine reaches network-online.

## 6. KIWI NG adapter

The first recipe targets Ubuntu 26.04 LTS with KDE/Kubuntu. It generates a KIWI ISO description, repository definitions, the root overlay containing the captured profile, Calamares integration and build scripts.

Native package providers are recipe-scoped. The Ubuntu recipe accepts APT-native profiles; it refuses Pacman/DNF/Zypper native package inventories instead of pretending package names are portable across distro families.

## 7. Security boundary

Known credential locations are excluded. Shell-like files have likely secret assignments redacted. Very large files are excluded by default. Browser profiles and personal documents are outside the default capture graph.

The security model is intentionally conservative but not a mathematical guarantee. A public-export workflow should eventually add a second secret scan over the final staged payload and an interactive review UI.
