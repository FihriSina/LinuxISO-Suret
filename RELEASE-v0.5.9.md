# Linux ISO - Suret v0.5.9 - Vendor-native application resolution

v0.5.9 follows the first Pardus Native run where the full distro/package phase succeeded, host-GPU Flatpak leakage was eliminated, Signal Flatpak deployed, but the captured APT installation of Visual Studio Code still failed after being translated to Flathub. The failure occurred inside Flatpak's `extra-data/apply_extra` bubblewrap path (`/proc/self/fd/...`), a class that also had upstream Flatpak 1.16.5 regressions.

## Application resolver changes

- Native Pardus no longer converts a captured APT `code` package into `com.visualstudio.code`.
- Native Pardus no longer converts a captured APT `signal-desktop` package into `org.signal.Signal`.
- Those source-native packages now resolve through a strict Suret vendor-APT allow-list:
  - Visual Studio Code -> Microsoft's official `packages.microsoft.com/repos/code` repository.
  - Signal Desktop -> Signal's official `updates.signal.org/desktop/apt` repository.
- The vendor signing keys and source files are installed into the target rootfs so normal APT updates continue after installation.
- The temporary Native build source list also receives only the selected allow-listed vendor sources; profile data cannot inject a repository URL, key path, shell fragment or package name.
- No Debian, Ubuntu, PPA or other distribution repository is introduced into the Pardus target.

## Provider fidelity

- A package captured as APT remains APT when a vetted vendor-native resolver exists.
- An application captured as Flatpak remains Flatpak.
- Snap captures continue to use explicitly allow-listed portable Flatpak mappings where available.
- Generic-mode launcher translations remain reversible. When Native Mode resolves Code/Signal back to vendor APT, their captured `.desktop` `Exec=` commands are restored from the existing `X-Suret-Original-Exec-B64` metadata instead of leaving `flatpak run ...` launchers behind.

## Flatpak containment

- Flatpak is no longer installed as a generic optional KDE package on every Pardus Native image.
- `flatpak` and `bubblewrap` are installed only when the source profile actually contains required Flatpak applications.
- Before true Flatpak deployment, Suret makes a final upgrade attempt using only the configured Pardus repositories and logs both Flatpak and bubblewrap versions.
- Flatpak 1.16.5 is explicitly diagnosed as having a known upstream `/proc/self/fd` sandbox regression fixed in 1.16.6. Suret does not add Debian repositories to obtain that fix.
- v0.5.8 host-GPU masking, generic GL selection and temporary bubblewrap privilege cleanup remain in place for true Flatpak profiles.

## Verification

- 220 regression tests pass.
- Python compile passes.
- Repository shell syntax checks pass.
- Generated Native staging has no unresolved template tokens.
- Generated Native scripts pass `bash -n`.
- Offline `uv lock --check` passes.

The existing verified profile can be reused; no source-desktop recapture is required.
