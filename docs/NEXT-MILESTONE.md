# Next milestone - v0.3.29 full desktop-surface acceptance

Re-scan the Pardus source with fidelity schema v7, build/install once, then validate the complete user-visible surface rather than isolated components:

- source-visible wallpaper is reproduced from live Plasma state, not a stale distro default
- localized desktop launchers such as `Bilgisayar` appear in the same desktop surface
- panel/dock geometry, widgets, task pins, Kickoff favorites/order, avatar, themes, cursor, fonts and window decoration match
- optional application cards start checked and use crisp scalable/high-resolution icons where available
- source-distro installer branding remains visible and Kubuntu branding does not leak into the Pardus profile
- installed QCOW2 boots without the ISO and keeps the captured desktop surface

The current technical image base remains Ubuntu/Kubuntu 26.04. Native per-distro package bases/installer engines remain a separate recipe milestone.
