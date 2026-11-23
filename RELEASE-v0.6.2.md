# Linux ISO - Suret v0.6.2

## SDDM + Plasma slideshow fidelity

v0.6.2 fixes two visual regressions observed in the first successful Pardus Native QEMU install: the login screen could render with a white/default background instead of the KDE Store customization, and a source Plasma slideshow was restored as a single static wallpaper.

### SDDM

- Reads SDDM theme settings in real precedence order: `/usr/lib/sddm/sddm.conf.d`, `/etc/sddm.conf.d`, then `/etc/sddm.conf`.
- Honors a custom `ThemeDir`.
- Copies the active SDDM theme and safely dereferences only symlinks whose targets remain inside the theme tree.
- Parses theme configuration files and promotes referenced external image assets (for example a `theme.conf.user` background under the user's Pictures directory) into `suret-assets/` inside the captured theme.
- Rewrites absolute source paths to target-portable theme-relative paths.
- Native restore removes only competing `[Theme]` keys from existing base SDDM configuration, leaves unrelated settings intact, and installs `10-suret-source-theme.conf`.
- Restored SDDM themes are fail-closed: missing theme payload or missing `Main.qml` aborts the Native build instead of silently shipping a divergent login screen.

### Plasma slideshow

- Stops converting `org.kde.slideshow` to `org.kde.image`.
- Preserves `SlidePaths`, interval/order/randomization and other slideshow keys from Plasma configuration.
- Captures runtime `SlidePaths` directories as well as the currently visible image.
- The most recent/current source slide is used only to seed `Image=` for first-frame fidelity; slideshow rotation remains active.
- Manifest records slideshow state and collection paths, and profile verification requires active slideshow collections to exist and contain images.

### Profile compatibility

The fidelity schema is now **11**. A v0.6.1-or-earlier real profile must be captured once again because older Suret releases deliberately flattened slideshow intent and could omit SDDM backgrounds stored outside the theme directory. `retry-native-acceptance.sh` detects this before resetting the Native work/result tree and instructs the user to run a fresh `native-acceptance.sh` pass.

### Validation

- 243 regression tests pass.
- Python compile checks pass.
- Native generated-script syntax/template checks are part of final artifact QA.
