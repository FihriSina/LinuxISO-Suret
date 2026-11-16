# Next milestone — v0.3 validation and fidelity

## Highest priority: prove the ISO

The v0.2 code can generate an Ubuntu 26.04 KDE KIWI + Calamares build project. The next milestone is not another abstraction layer; it is a reproducible VM validation loop.

1. Build the staged image with KIWI NG on a supported build host.
2. Boot the Live ISO with QEMU/KVM using UEFI and BIOS variants where practical.
3. Run Calamares into a disposable virtual disk.
4. Verify the installed system boots.
5. Compare the installed KDE state against the captured profile.
6. Verify package selection behavior with Internet available and unavailable.

## Fidelity work

- add safe symlink preservation for icon/theme/widget trees;
- detect custom system-wide themes/icons/cursors in `/usr/local/share` and package-unowned `/usr/share` content;
- produce a component -> asset -> package dependency graph;
- add AppStream display names/icons to installer applications;
- improve “installed later” classification using distro baseline/package history when reliable;
- add a final secret scan over the staged profile;
- make the audit fail on unresolved referenced Plasma widgets unless explicitly acknowledged.

## Installer UX

- create Linux ISO — Nakş Calamares branding;
- show one clear page per category or a custom single-page tree if that proves easier to use;
- show source/provider and download-size estimates;
- mark required appearance components separately from optional apps;
- show a warning when installation is offline and defer online selections cleanly.

## Distribution adapters

After the Ubuntu/KDE path passes the VM acceptance test:

1. Debian/APT recipe;
2. Arch/Pacman recipe;
3. Fedora/DNF recipe;
4. openSUSE/Zypper recipe;
5. package-name translation rules only where explicitly defined.

## Desktop adapters

After Plasma fidelity is stable:

- GNOME: dconf, extensions, shell theme, GTK/icon/cursor assets;
- Cinnamon;
- XFCE;
- optional standalone `.linux-iso` profile import without reinstalling Linux.

## Acceptance test

A source desktop containing all of the following must install into a clean VM without manual desktop reconstruction:

- two customized Plasma panels;
- third-party widgets;
- a widget or launcher using a manually downloaded SVG/PNG icon;
- custom wallpaper, icon theme, cursor and fonts;
- custom KWin script/effect;
- styled Konsole or another supported terminal;
- Zsh/Starship or equivalent shell styling;
- optional APT/Flatpak/Snap applications in multiple categories.
