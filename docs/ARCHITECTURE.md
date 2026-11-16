# Architecture

MyDistro is intentionally split into two artifacts:

1. **Portable personalization profile** — deterministic capture of the user's desktop experience.
2. **Distro-specific installer image** — a clean Live ISO that consumes the profile and installs selected applications online.

This avoids cloning hardware-specific state from a running machine into a new machine.

## Capture pipeline

```text
Source Linux
   |
   +-- System detector
   +-- Desktop adapter (v0.1: KDE Plasma)
   +-- Package inventory
   +-- Custom asset collector
   +-- Security sanitizer
   |
   v
manifest.yaml + payload/home/
```

### KDE adapter

The KDE adapter owns knowledge of Plasma/KDE locations and semantics. It captures the native Plasma configuration so panel geometry, applet order and applet configuration are preserved. It also captures user-local Plasma packages, themes, icons, wallpapers, fonts, Konsole profiles and `.desktop` overrides.

A generic asset pass then searches captured text configuration for direct references to image/font/sound files inside the source user's home directory. This catches one-off files such as `~/Pictures/icons/my-launcher.svg` that are not part of a formal icon theme.

### Home portability

Absolute source-home paths are rewritten from:

```text
/home/taha/Pictures/icons/foo.svg
```

to:

```text
{{HOME}}/Pictures/icons/foo.svg
```

The restore stage replaces `{{HOME}}` with the target user's actual home directory. Manifest source-path metadata uses the same placeholder, so exporting a profile does not expose the source username merely through file paths.

## Security boundary

The profile is meant to be shareable. Therefore the default capture set excludes known credential/key locations and never captures browser profiles or personal documents. Shell startup files are useful because they contain aliases, prompt configuration and shell plugins, but suspected secret assignments are redacted before export.

This is defense-in-depth, not a proof that arbitrary user configuration contains no secret. Before public distribution, a future release should include a review screen and secret-scanning pass over the finished profile.

## Package model

Applications are not embedded into the ISO by default. The manifest records installable package identifiers and an installer category. The eventual Calamares UI will present categories such as Internet, Development, Multimedia, Gaming and Communication.

Appearance dependencies are a special class. If a package is needed to reproduce the source appearance, it should be preselected and disabling it should warn that visual fidelity may be reduced.

## Future ISO pipeline

```text
Portable profile
      |
      v
Distro builder adapter
      |
      +-- KIWI image description / distro repositories
      +-- profile overlay in /usr/share/mydistro/profile
      +-- first-login profile applier
      +-- Calamares application-selection module
      |
      v
Bootable Live ISO
```

The ISO builder must be distro-aware. A single recipe should not blindly mix Debian/Ubuntu, Arch, Fedora and openSUSE package/repository semantics.
