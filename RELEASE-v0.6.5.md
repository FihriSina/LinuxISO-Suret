# Linux ISO - Suret v0.6.5

## Pardus Software Center contention hardening

v0.6.5 targets a QEMU-only post-login freeze seen when opening Pardus Software Center immediately after authentication. The remaster now refreshes installed `pardus-software` and `pardus-update` packages from the same isolated official Pardus 25 repositories used by Native build operations.

The generated Suret acceptance VM is marked with SMBIOS product `Suret-QEMU-Test`. Only in that marked VM, pre-login creates XDG user overrides that suppress Pardus Update / package update notifier / Discover notifier autostarts, and first-login suspends Baloo indexing. This prevents concurrent apt metadata scans from competing with the software center during acceptance testing. Physical installs and unrelated VMs are unaffected.

The QEMU quieting override is applied after profile restore and refuses to follow user-controlled `.config`/`autostart` symlinks. Native Pardus launchers continue to restore `pardus-software` rather than forcing Plasma Discover.

The profile schema is unchanged from v0.6.3/v0.6.4; no recapture is required when an existing schema-12 profile is already available.
