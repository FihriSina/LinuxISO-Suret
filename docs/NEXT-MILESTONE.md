# Next milestone - v0.6.2 Native Pardus visual acceptance

The next validation target is a fresh Pardus 25.2 Native capture/build that proves the two newly fixed visual states on both Live and installed-system boots:

- KDE Store SDDM login theme/background is visible instead of a white fallback.
- Plasma desktop keeps the captured slideshow active and rotates through the captured image collection.

Because v0.6.1 and older profiles intentionally flattened slideshow state and did not bundle external SDDM background files, v0.6.2 requires **one fresh source capture**. Do not use retry for the first v0.6.2 run.

Run:

```bash
cd ~/Kodlama/LinuxISO-Suret

./scripts/native-acceptance.sh \
  "$HOME/İndirilenler/Pardus-25.2-XFCE-amd64.iso"
```

Before the build starts, the application/visual plan should report the captured SDDM theme and slideshow state, for example:

```text
- SDDM theme: <theme-name> (1 external asset(s))
- Plasma slideshow: active (1 collection path(s))
```

Expected Native chain:

1. Fresh schema-v11 profile capture and verification.
2. Pardus ISO probe and Native staging.
3. KDE/SDDM, appearance dependencies and captured applications install inside the Pardus rootfs.
4. Captured SDDM theme is installed as `/usr/share/sddm/themes/suret-source`; competing base `[Theme]` keys are neutralized without touching unrelated SDDM settings.
5. User profile is applied pre-login with the slideshow plugin and complete slide collection intact.
6. Live metadata, squashfs and ISO checksums are rebuilt.
7. Boot metadata is preserved and verified.
8. QEMU validates Live boot, Pardus installer and installed-system boot.

Acceptance criteria:

- SDDM does not fall back to a white/default background.
- The selected KDE Store login theme renders with its captured custom background.
- Plasma `wallpaperplugin` remains `org.kde.slideshow` when that is the source state.
- `SlidePaths` resolves only to payload-backed portable paths.
- Multiple slideshow images are present on the target and change according to the captured slideshow settings.
- Existing panel/Kickoff/avatar/theme/application fidelity remains unchanged.
- ChatGPT/other Brave-bound web apps still open in Brave app-window mode rather than the default browser.
- No browser profile, cookies, passwords, tokens or other credential data is introduced.

After this visual acceptance passes, later work can focus on optional XFCE removal and broader Native distro adapters rather than further first-boot fidelity repair.
