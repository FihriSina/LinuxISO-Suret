# Linux ISO - Suret v0.4.1

v0.4.1 changes the debugging model from one-error-per-build to batch convergence.

## Runtime fidelity fixes

- The running Plasma primary screen (screen 0) is authoritative for `visible_wallpaper` when D-Bus runtime state is available. Persisted configurations from dormant/secondary containments can no longer win merely because their `Image=` line appears first.
- First-login convergence actively reapplies the captured icon theme, cursor theme, color scheme and Plasma desktop theme as well as the visible wallpaper.
- The first-login marker is tied to a hash of the visible-state payload rather than only the schema number.
- A first-login report records requested and observed wallpaper state plus appearance-application results.

## Batch diagnostics

The installed/live image now includes:

```bash
suret-diagnose
```

It creates a redacted `~/suret-diagnostics-*.tar.gz` containing the major evidence needed for a single multi-error debugging pass:

- runtime Plasma wallpaper/containment state;
- Suret first-login and target-profile markers;
- relevant KDE configuration;
- desktop launcher metadata and executable health;
- `computer:/` KIO test;
- required package/command availability;
- failed systemd units, storage/mount and UEFI information;
- captured GRUB/SDDM fidelity configuration;
- filtered Plasma/SDDM/KWin/KIO/GRUB/Calamares/Suret journal events.

Username, home path and hostname strings are redacted from the diagnostic payload.

## Validation

- 130/130 regression tests pass.
- Generated first-login Python compiles.
- Generated QEMU and `suret-diagnose` shell scripts pass `bash -n`.
- The diagnostic collector was smoke-tested to create and unpack its archive successfully.
