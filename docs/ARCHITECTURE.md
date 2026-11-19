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

Native mode intentionally refuses silent cross-distro grafting. If the profile was captured from Pardus, the selected native base must also be Pardus.

## Secondary path: Generic Build Mode

The existing KIWI + Ubuntu/Kubuntu + Calamares pipeline remains available for experimental/custom base images:

```text
Portable Profile → KIWI recipe → Calamares → Generic Live ISO
```

This mode is no longer the preferred path when the user wants the resulting system to remain genuinely Pardus/Fedora/etc.

## Capture and profile rules

- Active-only appearance capture remains the default.
- `verify` validates payload integrity and required appearance dependencies.
- Source-home paths remain normalized to `{{HOME}}`.
- Known credential stores and likely secrets remain excluded/redacted.
- Application identity retains provider (`apt`, `dnf`, `pacman`, `flatpak`, etc.) rather than pretending package names are universally portable.

## Native remaster boundary

The native adapter operates on the user's supplied ISO rather than reconstructing the distro from another base. For Pardus 25 this means preserving the official GRUB/ISOLINUX tree, `pardus-installer`, APT identity and `/live/filesystem.squashfs`, while changing the live filesystem contents.

## Launcher resolution in Native Mode

Capture may carry Generic Mode compatibility translations, but it also stores the source `Exec=` contract in reversible Suret metadata. The Native adapter removes that metadata and restores same-distro commands. Only browser/web launchers and explicitly mapped third-party vendor applications remain portable fallbacks. This keeps Pardus-native tools native while avoiding broken third-party favorites when the official ISO does not contain a user's external APT repository.
