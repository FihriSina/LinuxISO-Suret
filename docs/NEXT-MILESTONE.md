# v0.2 / v0.3 implementation target

## v0.2 — fidelity validator

- Add `mydistro audit` to report every captured custom asset and its consumer.
- Build component -> package dependency graph.
- Identify referenced Plasma plugin IDs and distinguish:
  - Plasma built-ins
  - user-local plasmoids already captured in payload
  - system-wide third-party plasmoids that must be reinstalled online
- Preserve safe symlinks and POSIX mode bits.
- Add profile size report and large-file opt-in.
- Test capture -> restore inside a disposable Plasma 6 VM.

## v0.3 — first installable ISO

Target one concrete base first: Debian 13 + KDE Plasma or Ubuntu 26.04 + Plasma.

- Generate a KIWI image description for that target.
- Put the exported profile under `/usr/share/mydistro/profile` in the Live image.
- Add a target-user restore service that runs after Calamares creates the user.
- Add a Calamares page for categorized online application selection.
- Split applications into:
  - required for appearance
  - recommended
  - optional
- Install online packages into the target root, not the Live session.
- Validate boot and installation in QEMU/KVM before writing to physical media.

## Acceptance test

Given a source Plasma desktop with:

- two custom panels,
- third-party plasmoids,
- a launcher using a manually downloaded SVG icon,
- a custom wallpaper,
- a cursor/icon/theme set,
- a Konsole profile,
- Starship/Zsh styling,

then a clean VM installed from the generated ISO should open into the same layout without manually adding panels, widgets, themes or icons. Optional applications should only be installed if selected in the installer.
