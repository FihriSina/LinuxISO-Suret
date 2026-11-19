# Linux ISO - Suret v0.4.0

v0.4.0 is the final acceptance baseline for the current Ubuntu 26.04 KDE recipe.

## Final acceptance command

```bash
./scripts/final-acceptance.sh
```

This command re-captures the current source desktop with fidelity schema v9, verifies and audits it, builds the ISO, creates a clean 40 GiB QEMU disk, and starts the installer VM.

When Calamares reaches **Done / Restart**, leave the QEMU window open. The ISO is configured as a one-time boot source, so the same VM reboots directly into the newly installed disk. No second `installed` command is required for the normal acceptance path.

## Acceptance scope

The captured, non-personal visible state includes Plasma layout, wallpaper assets, panel/task launchers, Kickoff favorites/order, icon/cursor/theme assets, desktop launchers, avatar, SDDM appearance, GRUB appearance when a source theme/background is discoverable, and source-distribution installer branding. Known credential stores and personal documents remain excluded.

The current build substrate is Ubuntu 26.04 KDE + KIWI + Calamares. Native Fedora/Anaconda or a different native source-distribution package base is future scope rather than a v0.4.0 blocker.
