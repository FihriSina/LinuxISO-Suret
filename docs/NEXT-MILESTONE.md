# Next milestone - v0.3.28 source-native installer + full fidelity validation

Re-scan the Pardus source with fidelity schema v6, build and install the ISO, then validate:

- live desktop wallpaper, panel, icons, themes and Kickoff favorites against the source
- installer product name/logo/colors contain no visible Kubuntu branding for a Pardus profile
- installation slideshow uses source imagery
- every optional application card starts checked and can be unchecked independently
- captured app icons render when available and fallback covers render otherwise
- installed QCOW2 still boots without ISO and retains the source desktop state

The technical build base remains Ubuntu/Kubuntu 26.04 for the current recipe. A genuinely native Fedora Anaconda or distro-specific package base is a separate future recipe/installer-engine milestone, not a branding substitution.
