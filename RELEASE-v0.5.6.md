# Linux ISO - Suret v0.5.6 - Native APT Media Isolation

v0.5.6 fixes the first real package-installation failure reached by the Pardus 25.2 Native remaster pipeline.

## Root cause

The stock Pardus live rootfs contains an APT source for the live medium (`file:/run/live/medium`). During a Suret remaster the chroot has an intentionally isolated tmpfs `/run`, and the extracted ISO does not provide a Debian repository at that path. `apt-get update` therefore downloaded the valid Pardus network indexes but still exited with code 100 because the local-media source had no `dists/yirmibes-deb/.../Packages` index.

## Fix

- Native package installation no longer consumes the live system's APT source configuration directly.
- Pardus 25 builds use a build-only source list under `/run/linux-iso/apt-build`, populated with the official Pardus 25 `yirmibes`, `yirmibes-deb`, and security repositories.
- APT source-parts and list state are isolated under `/run` too, so stale/local-media indexes cannot participate in dependency resolution.
- The ISO's original `/etc/apt/sources.list*` configuration is not rewritten, quarantined, or deleted; the live session and Pardus installer retain the distro-provided configuration.
- Build-time APT disables translations and `Contents` indexes because package installation does not require them, reducing metadata traffic and retry time.
- All package availability checks now use the same isolated APT configuration as package installation.

## Validation

- Adds executable regression coverage for build-only APT source generation and source/index isolation.
- Verifies the generated configuration contains no `file:/run/live/medium` or `cdrom:` source.
- Verifies the Native install template does not rewrite the final ISO's APT source files.
- 200/200 regression tests pass.
