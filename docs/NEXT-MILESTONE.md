# Post-v0.4.0

v0.4.0 is the final acceptance baseline for the Ubuntu/KDE recipe. Future work should be treated as new scope (for example native Fedora/Anaconda or native Pardus base recipes), not as blockers for the current Suret pipeline.

# Next milestone - v0.3.33 acceptance

1. Reuse the freshly captured v8 profile or re-scan once.
2. Run `safe-first-iso.sh`; it must pass the schema gate and create the build directory.
3. Build ISO, run live QEMU, install, then boot the installed qcow2 system.

# Next milestone - v0.3.32 acceptance

Validate in QEMU: source-like GRUB menu, source SDDM/login appearance, working Bilgisayar launcher, avatar, and installed-system desktop fidelity.

# Next milestone - v0.3.31 acceptance

Validate that the live desktop visibly contains the source-branded installer shortcut and that installed mode boots the qcow2 disk after Calamares finishes.
