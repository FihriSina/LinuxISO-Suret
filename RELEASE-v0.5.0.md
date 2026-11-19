# Linux ISO - Suret v0.5.0 — Native ISO Mode foundation

v0.5.0 changes the primary architecture from "make Ubuntu/Kubuntu look like the source" to "remaster the user's own distro ISO".

## Pardus-first native mode

- `linux-iso probe-iso BASE.iso` detects the supplied ISO, live rootfs, package family and installer.
- Pardus 25 live ISOs using `/live/filesystem.squashfs` are the first build-capable adapter.
- `linux-iso stage-native PROFILE BASE.iso` creates a remaster project that preserves the base ISO bootloader, repositories, kernel family, distro identity and Pardus installer.
- A KDE source profile causes KDE Plasma to be installed inside the Pardus rootfs using Pardus/Debian-family repositories rather than switching the OS base to Ubuntu.
- The default policy keeps the native XFCE/GNOME packages for installer/live safety while making Plasma available; `--replace-base-desktop` can remove XFCE after KDE is installed.
- User-facing native packages from the capture manifest are installed when the base distro repository provides them. Flatpaks are installed system-wide from Flathub when possible.
- The profile is embedded and converged for both live and installed users on first login.
- The original ISO boot catalog is replayed by xorriso; Pardus GRUB and native installer remain authoritative.

## Safety boundary

Native mode refuses silent cross-distro grafting. A Pardus profile must use a Pardus base ISO. Fedora and Ubuntu can be probed, but the first build-capable adapter is Pardus/Debian live ISO layout.

## One-command path

```bash
./scripts/native-acceptance.sh ~/Downloads/Pardus-25.2-XFCE-amd64.iso
```

The previous KIWI Ubuntu/Kubuntu Generic Build Mode remains available through `stage-iso` / `build-iso` for experimental use.

## First-frame fidelity

Native mode installs a pre-login systemd convergence service. On the installed system it applies the captured home profile and avatar before the first display-manager login, reducing the old cursor/font/wallpaper transition seen with post-login-only restoration. Captured GRUB/SDDM visual state is also applied inside the native root filesystem when available.

## Native compatibility resolver

- Capture now records a reversible copy of every launcher `Exec=` line that Suret translates for Generic Mode.
- Native Mode restores original distro-native launchers when the supplied base ISO matches the captured distro. Pardus tools therefore stay Pardus tools instead of being redirected to Kubuntu/KDE substitutes.
- Known third-party packages that commonly depend on external repositories (`code`, Signal, Steam, Discord, Spotify, OBS, Brave, Chrome) resolve to known Flatpak application IDs in Native Mode.
- Required captured Flatpaks are treated as build requirements: the remaster fails explicitly rather than shipping a favorite that cannot launch.
- If a Pardus live rootfs has no network Pardus repository configured, Suret adds the official Pardus 25 `yirmibes`, `yirmibes-deb` and security repositories before installing KDE.

## First-frame appearance

- The pre-login profile service refreshes the target user's font cache before the first Plasma session.
- Captured user-local cursor themes and fonts are promoted to system-visible locations for SDDM, reducing cursor/font changes between login screen and desktop.
